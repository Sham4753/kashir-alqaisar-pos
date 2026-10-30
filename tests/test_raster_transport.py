import unittest
from unittest.mock import patch

import test_security_and_print as fixture_module

server = fixture_module.server


class _Connection:
    def __init__(self, behavior, received):
        self.behavior = behavior
        self.received = received
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def send(self, payload):
        self.calls += 1
        action = self.behavior[self.calls - 1]
        if action == 'error':
            raise OSError('dropped')
        count = min(int(action), len(payload))
        self.received.append(bytes(payload[:count]))
        return count


class RasterTransportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_feed_is_preserved_when_cut_is_disabled(self):
        payload = server.render_escpos_raster_payload_for_printer(
            'اختبار', {'paper_width': 58, 'cut_enabled': False, 'feed_before_cut': 3}
        )
        self.assertTrue(payload.endswith(b'\n\n\n'))
        self.assertNotIn(b'\x1d\x56', payload)

    def test_long_raster_is_split_into_small_gs_v_zero_frames(self):
        raw = bytes(range(251)) * 17
        raw = (raw * ((4100 // len(raw)) + 1))[:4100]
        payload = server.escpos_raster_frames(1, raw, 4100, max_frame_height=4096)
        self.assertTrue(payload.startswith(b'\x1b\x40\x1d\x76\x30\x00'))
        first_height = int.from_bytes(payload[8:10], 'little')
        second_header = 2 + 8 + first_height
        second_height = int.from_bytes(payload[second_header + 6:second_header + 8], 'little')
        self.assertEqual((first_height, second_height), (4096, 4))
        rebuilt = payload[10:10 + first_height] + payload[second_header + 8:]
        self.assertEqual(rebuilt, raw)

    def test_network_retry_resumes_from_bytes_already_accepted(self):
        received = []
        connections = [
            _Connection([2, 'error'], received),
            _Connection([4], received),
        ]
        with patch.object(server, 'render_escpos_raster_payload_for_printer', return_value=b'abcdef'), \
             patch.object(server.socket, 'create_connection', side_effect=connections):
            result = server.submit_network_raw_print('192.0.2.50', 9100, 'x', printer_config={'printer_retry_count': 1})
        self.assertTrue(result['ok'])
        self.assertEqual(received, [b'ab', b'cdef'])
        self.assertEqual(b''.join(received), b'abcdef')

    def test_print_worker_failure_marks_queued_record_failed(self):
        data = server.load()
        data['print_log'] = [{'id': 'queued-exception', 'status': 'queued', 'message': ''}]
        server.save(data)
        server.mark_print_job_failed('queued-exception', RuntimeError('renderer crashed'))
        row = next(row for row in server.load()['print_log'] if row['id'] == 'queued-exception')
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['message'], 'renderer crashed')

    def test_narrow_layout_matches_58mm_exactly(self):
        for paper_width, expected in ((58, '28,16,28,28'), (80, '40,17,22,21'), (57, '40,17,22,21')):
            data = {'settings': {'printer': {'paper_width': paper_width}}}
            order = {'id': 'NARROW', 'items': []}
            with self.subTest(paper_width=paper_width):
                self.assertIn(expected, server.thermal_receipt_structured(data, order))


if __name__ == '__main__':
    unittest.main()

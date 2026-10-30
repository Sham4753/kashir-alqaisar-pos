#define UNICODE
#define _UNICODE
#include <winsock2.h>
#include <windows.h>
#include <ws2tcpip.h>
#include <shellapi.h>
#include <shlwapi.h>
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "shlwapi.lib")

static BOOL port_open(void) {
    WSADATA wsa; SOCKET s; struct sockaddr_in addr; int ok;
    if (WSAStartup(MAKEWORD(2,2), &wsa) != 0) return FALSE;
    s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET) { WSACleanup(); return FALSE; }
    addr.sin_family = AF_INET; addr.sin_port = htons(8080); addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    ok = connect(s, (struct sockaddr*)&addr, sizeof(addr)) == 0;
    closesocket(s); WSACleanup(); return ok;
}

static BOOL start_server(const wchar_t *root, const wchar_t *appdir) {
    wchar_t python[MAX_PATH], server[MAX_PATH], logpath[MAX_PATH], command[MAX_PATH * 3];
    STARTUPINFOW si; PROCESS_INFORMATION pi; HANDLE log;
    wsprintfW(python, L"%s\\python.exe", root);
    wsprintfW(server, L"%s\\server.py", appdir);
    wsprintfW(logpath, L"%s\\server_error.log", appdir);
    log = CreateFileW(logpath, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (log == INVALID_HANDLE_VALUE) return FALSE;
    ZeroMemory(&si, sizeof(si)); si.cb = sizeof(si); si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdOutput = log; si.hStdError = log; si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    ZeroMemory(&pi, sizeof(pi));
    wsprintfW(command, L"\"%s\" \"%s\"", python, server);
    if (!CreateProcessW(NULL, command, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, appdir, &si, &pi)) {
        CloseHandle(log); return FALSE;
    }
    CloseHandle(pi.hProcess); CloseHandle(pi.hThread); CloseHandle(log);
    return TRUE;
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE prev, LPSTR cmd, int show) {
    wchar_t exe[MAX_PATH], appdir[MAX_PATH], root[MAX_PATH], params[512];
    int i;
    GetModuleFileNameW(NULL, exe, MAX_PATH);
    lstrcpyW(appdir, exe); PathRemoveFileSpecW(appdir);
    lstrcpyW(root, appdir); PathRemoveFileSpecW(root);
    if (!port_open() && !start_server(root, appdir)) {
        MessageBoxW(NULL, L"تعذر بدء Python المضمّن. راجع الملف app\\server_error.log وتأكد من فك ضغط الحزمة كاملة.", L"كاشير قيصر", MB_ICONERROR | MB_OK);
        return 1;
    }
    for (i = 0; i < 60 && !port_open(); i++) Sleep(250);
    if (!port_open()) {
        MessageBoxW(NULL, L"تعذر تشغيل خادم كاشير قيصر. راجع app\\server_error.log لمعرفة السبب.", L"كاشير قيصر", MB_ICONERROR | MB_OK);
        return 1;
    }
    lstrcpyW(params, L"--app=http://127.0.0.1:8080/ --new-window --window-size=1280,820");
    if ((INT_PTR)ShellExecuteW(NULL, L"open", L"msedge.exe", params, appdir, SW_SHOWNORMAL) <= 32) {
        MessageBoxW(NULL, L"تعذر العثور على Microsoft Edge لتشغيل CAESAR كنافذة تطبيق مستقلة. ثبّت Edge ثم أعد المحاولة.", L"CAESAR POS", MB_ICONERROR | MB_OK);
        return 1;
    }
    return 0;
}

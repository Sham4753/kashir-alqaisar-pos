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

static void start_server(const wchar_t *root, const wchar_t *appdir) {
    wchar_t python[MAX_PATH], server[MAX_PATH], command[MAX_PATH * 3];
    STARTUPINFOW si; PROCESS_INFORMATION pi;
    wsprintfW(python, L"%s\\pythonw.exe", root);
    wsprintfW(server, L"%s\\server.py", appdir);
    wsprintfW(command, L"\"%s\" \"%s\"", python, server);
    ZeroMemory(&si, sizeof(si)); si.cb = sizeof(si);
    ZeroMemory(&pi, sizeof(pi));
    CreateProcessW(NULL, command, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, appdir, &si, &pi);
    if (pi.hProcess) CloseHandle(pi.hProcess);
    if (pi.hThread) CloseHandle(pi.hThread);
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE prev, LPSTR cmd, int show) {
    wchar_t exe[MAX_PATH], appdir[MAX_PATH], root[MAX_PATH], params[512];
    int i;
    GetModuleFileNameW(NULL, exe, MAX_PATH);
    lstrcpyW(appdir, exe); PathRemoveFileSpecW(appdir);
    lstrcpyW(root, appdir); PathRemoveFileSpecW(root);
    if (!port_open()) start_server(root, appdir);
    for (i = 0; i < 50 && !port_open(); i++) Sleep(200);
    if (!port_open()) {
        MessageBoxW(NULL, L"تعذر تشغيل خادم كاشير القيصر. تأكد من وجود ملفات النظام في المجلد نفسه.", L"كاشير القيصر", MB_ICONERROR | MB_OK);
        return 1;
    }
    lstrcpyW(params, L"--app=http://127.0.0.1:8080/ --window-size=1280,820");
    if ((INT_PTR)ShellExecuteW(NULL, L"open", L"msedge.exe", params, appdir, SW_SHOWNORMAL) <= 32) {
        ShellExecuteW(NULL, L"open", L"http://127.0.0.1:8080/", NULL, appdir, SW_SHOWNORMAL);
    }
    return 0;
}

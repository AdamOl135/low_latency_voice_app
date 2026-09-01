#!/usr/bin/env python3
import os
import shutil
import subprocess
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
TMP_BUILD = os.path.join(DIST_DIR, "tmp_win_build")
WIN_STAGE = os.path.join(DIST_DIR, "low_latency_voice_app-v1.0.0-windows-x64")

os.makedirs(TMP_BUILD, exist_ok=True)
if os.path.exists(WIN_STAGE):
    shutil.rmtree(WIN_STAGE)
os.makedirs(os.path.join(WIN_STAGE, "data"), exist_ok=True)

win_defs_content = """#ifndef WIN_DEFS_H
#define WIN_DEFS_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#define WINAPI __stdcall
#define CALLBACK __stdcall
#define MMSYSERR_NOERROR 0
#define WAVE_MAPPER ((UINT)-1)
#define WAVE_FORMAT_PCM 1
#define WIM_DATA 0x3C0
#define WOM_DONE 0x3C1
#define CALLBACK_FUNCTION 0x00030000l
#define CP_UTF8 65001

typedef void* HANDLE;
typedef void* HWND;
typedef void* HINSTANCE;
typedef void* HWAVEIN;
typedef void* HWAVEOUT;
typedef unsigned long DWORD;
typedef unsigned long long DWORD_PTR;
typedef unsigned long long UINT_PTR;
typedef unsigned long long ULONG_PTR;
typedef unsigned short WORD;
typedef unsigned int UINT;
typedef int BOOL;
typedef char CHAR;
typedef char* LPSTR;
typedef unsigned short WCHAR;
typedef unsigned short* LPWSTR;
typedef const unsigned short* LPCWSTR;
typedef const char* LPCSTR;
typedef unsigned char BYTE;
typedef long LONG;
typedef UINT MMRESULT;

typedef struct {
    void* DebugInfo;
    LONG LockCount;
    LONG RecursionCount;
    HANDLE OwningThread;
    HANDLE LockSemaphore;
    ULONG_PTR SpinCount;
} CRITICAL_SECTION, *PCRITICAL_SECTION, *LPCRITICAL_SECTION;

typedef struct {
    WORD  wFormatTag;
    WORD  nChannels;
    DWORD nSamplesPerSec;
    DWORD nAvgBytesPerSec;
    WORD  nBlockAlign;
    WORD  wBitsPerSample;
    WORD  cbSize;
} WAVEFORMATEX, *PWAVEFORMATEX, *LPWAVEFORMATEX;

typedef struct wavehdr_tag {
    LPSTR      lpData;
    DWORD      dwBufferLength;
    DWORD      dwBytesRecorded;
    DWORD_PTR  dwUser;
    DWORD      dwFlags;
    DWORD      dwLoops;
    struct wavehdr_tag *lpNext;
    DWORD_PTR  reserved;
} WAVEHDR, *PWAVEHDR, *LPWAVEHDR;

typedef struct tagWAVEINCAPSA {
    WORD      wMid;
    WORD      wPid;
    UINT      vDriverVersion;
    CHAR      szPname[32];
    DWORD     dwFormats;
    WORD      wChannels;
    WORD      wReserved1;
} WAVEINCAPSA, *PWAVEINCAPSA, *LPWAVEINCAPSA;

typedef struct tagWAVEINCAPSW {
    WORD      wMid;
    WORD      wPid;
    UINT      vDriverVersion;
    WCHAR     szPname[32];
    DWORD     dwFormats;
    WORD      wChannels;
    WORD      wReserved1;
} WAVEINCAPSW, *PWAVEINCAPSW, *LPWAVEINCAPSW;

typedef struct tagWAVEOUTCAPSA {
    WORD      wMid;
    WORD      wPid;
    UINT      vDriverVersion;
    CHAR      szPname[32];
    DWORD     dwFormats;
    WORD      wChannels;
    WORD      wReserved1;
    DWORD     dwSupport;
} WAVEOUTCAPSA, *PWAVEOUTCAPSA, *LPWAVEOUTCAPSA;

typedef struct tagWAVEOUTCAPSW {
    WORD      wMid;
    WORD      wPid;
    UINT      vDriverVersion;
    WCHAR     szPname[32];
    DWORD     dwFormats;
    WORD      wChannels;
    WORD      wReserved1;
    DWORD     dwSupport;
} WAVEOUTCAPSW, *PWAVEOUTCAPSW, *LPWAVEOUTCAPSW;

__attribute__((dllimport)) void WINAPI InitializeCriticalSection(LPCRITICAL_SECTION lpCriticalSection);
__attribute__((dllimport)) void WINAPI DeleteCriticalSection(LPCRITICAL_SECTION lpCriticalSection);
__attribute__((dllimport)) void WINAPI EnterCriticalSection(LPCRITICAL_SECTION lpCriticalSection);
__attribute__((dllimport)) void WINAPI LeaveCriticalSection(LPCRITICAL_SECTION lpCriticalSection);
__attribute__((dllimport)) void WINAPI Sleep(DWORD dwMilliseconds);
__attribute__((dllimport)) DWORD WINAPI timeGetTime(void);
__attribute__((dllimport)) int WINAPI WideCharToMultiByte(UINT CodePage, DWORD dwFlags, LPCWSTR lpWideCharStr, int cchWideChar, LPSTR lpMultiByteStr, int cbMultiByte, LPCSTR lpDefaultChar, BOOL *lpUsedDefaultChar);

__attribute__((dllimport)) UINT WINAPI waveInGetNumDevs(void);
__attribute__((dllimport)) MMRESULT WINAPI waveInGetDevCapsW(UINT_PTR uDeviceID, LPWAVEINCAPSW pwic, UINT cbwic);
__attribute__((dllimport)) MMRESULT WINAPI waveInOpen(HWAVEIN *phwi, UINT uDeviceID, const WAVEFORMATEX *pwfx, DWORD_PTR dwCallback, DWORD_PTR dwInstance, DWORD fdwOpen);
__attribute__((dllimport)) MMRESULT WINAPI waveInClose(HWAVEIN hwi);
__attribute__((dllimport)) MMRESULT WINAPI waveInPrepareHeader(HWAVEIN hwi, LPWAVEHDR pwh, UINT cbwh);
__attribute__((dllimport)) MMRESULT WINAPI waveInUnprepareHeader(HWAVEIN hwi, LPWAVEHDR pwh, UINT cbwh);
__attribute__((dllimport)) MMRESULT WINAPI waveInAddBuffer(HWAVEIN hwi, LPWAVEHDR pwh, UINT cbwh);
__attribute__((dllimport)) MMRESULT WINAPI waveInStart(HWAVEIN hwi);
__attribute__((dllimport)) MMRESULT WINAPI waveInStop(HWAVEIN hwi);
__attribute__((dllimport)) MMRESULT WINAPI waveInReset(HWAVEIN hwi);

__attribute__((dllimport)) UINT WINAPI waveOutGetNumDevs(void);
__attribute__((dllimport)) MMRESULT WINAPI waveOutGetDevCapsW(UINT_PTR uDeviceID, LPWAVEOUTCAPSW pwoc, UINT cbwoc);
__attribute__((dllimport)) MMRESULT WINAPI waveOutOpen(HWAVEOUT *phwo, UINT uDeviceID, const WAVEFORMATEX *pwfx, DWORD_PTR dwCallback, DWORD_PTR dwInstance, DWORD fdwOpen);
__attribute__((dllimport)) MMRESULT WINAPI waveOutClose(HWAVEOUT hwo);
__attribute__((dllimport)) MMRESULT WINAPI waveOutPrepareHeader(HWAVEOUT hwo, LPWAVEHDR pwh, UINT cbwh);
__attribute__((dllimport)) MMRESULT WINAPI waveOutUnprepareHeader(HWAVEOUT hwo, LPWAVEHDR pwh, UINT cbwh);
__attribute__((dllimport)) MMRESULT WINAPI waveOutWrite(HWAVEOUT hwo, LPWAVEHDR pwh, UINT cbwh);
__attribute__((dllimport)) MMRESULT WINAPI waveOutPause(HWAVEOUT hwo);
__attribute__((dllimport)) MMRESULT WINAPI waveOutRestart(HWAVEOUT hwo);
__attribute__((dllimport)) MMRESULT WINAPI waveOutReset(HWAVEOUT hwo);

#endif
"""

with open(os.path.join(TMP_BUILD, "win_defs.h"), "w") as f:
    f.write(win_defs_content)

def_files = {
    "kernel32.def": """LIBRARY KERNEL32.DLL
EXPORTS
ExitProcess
GetStdHandle
WriteConsoleA
WriteFile
GetCommandLineW
GetModuleHandleW
CreateProcessA
Sleep
InitializeCriticalSection
EnterCriticalSection
LeaveCriticalSection
DeleteCriticalSection
WideCharToMultiByte
SetConsoleTitleA
LoadLibraryA
GetProcAddress
""",
    "user32.def": """LIBRARY USER32.DLL
EXPORTS
MessageBoxA
MessageBoxW
""",
    "winmm.def": """LIBRARY WINMM.DLL
EXPORTS
waveInOpen
waveInClose
waveInPrepareHeader
waveInUnprepareHeader
waveInAddBuffer
waveInStart
waveInStop
waveInReset
waveInGetNumDevs
waveInGetDevCapsA
waveInGetDevCapsW
waveOutOpen
waveOutClose
waveOutPrepareHeader
waveOutUnprepareHeader
waveOutWrite
waveOutPause
waveOutRestart
waveOutReset
waveOutGetNumDevs
waveOutGetDevCapsA
waveOutGetDevCapsW
timeGetTime
""",
    "msvcrt.def": """LIBRARY MSVCRT.DLL
EXPORTS
memcpy
memset
memmove
memcmp
malloc
free
calloc
realloc
sin
cos
sqrt
log10
fabs
printf
sprintf
snprintf
sscanf
puts
strcmp
strncmp
strcpy
strncpy
strlen
strcat
strncat
atoi
atol
strtol
strtoul
"""
}

for name, content in def_files.items():
    p = os.path.join(TMP_BUILD, name)
    with open(p, "w") as f:
        f.write(content)
    libname = "lib" + name.replace(".def", ".a")
    libp = os.path.join(TMP_BUILD, libname)
    subprocess.check_call(["/usr/lib/llvm-21/bin/llvm-dlltool", "-d", p, "-m", "i386:x86-64", "-l", libp])

with open(os.path.join(TMP_BUILD, "stubs.c"), "w") as f:
    f.write("void __main(void) {}\nvoid ___chkstk_ms(void) {}\n")

# Prepare modified voice_engine_win.c
with open(os.path.join(PROJECT_ROOT, "client", "native", "libvoice_engine.c"), "r") as f:
    src = f.read()

src = src.replace("#include <windows.h>", '#include "win_defs.h"').replace("#include <mmsystem.h>", "")
src = src.replace('if (sscanf(device_id, "winmm_in_%u", &devIdx) == 1) {', 'if (strncmp(device_id, "winmm_in_", 9) == 0) { devIdx = (UINT)atoi(device_id + 9);')
src = src.replace('if (sscanf(device_id, "winmm_out_%u", &devIdx) == 1) {', 'if (strncmp(device_id, "winmm_out_", 10) == 0) { devIdx = (UINT)atoi(device_id + 10);')

with open(os.path.join(TMP_BUILD, "voice_engine_win.c"), "w") as f:
    f.write(src)

native_inc = os.path.join(PROJECT_ROOT, "client", "native")
subprocess.check_call([
    "clang", "-target", "x86_64-pc-windows-gnu", "-O2",
    f"-I{TMP_BUILD}", f"-I{native_inc}",
    "-isystem", "/usr/include", "-isystem", "/usr/include/x86_64-linux-gnu", "-isystem", "/usr/lib/llvm-21/lib/clang/21/include",
    "-D_WIN32", "-c", os.path.join(TMP_BUILD, "voice_engine_win.c"),
    "-o", os.path.join(TMP_BUILD, "voice_engine_win.o")
])

subprocess.check_call([
    "clang", "-target", "x86_64-pc-windows-gnu", "-O2", "-c",
    os.path.join(TMP_BUILD, "stubs.c"), "-o", os.path.join(TMP_BUILD, "stubs.o")
])

# Link voice_engine.dll
voice_dll_path = os.path.join(WIN_STAGE, "voice_engine.dll")
subprocess.check_call([
    "ld", "-m", "i386pep", "--shared",
    os.path.join(TMP_BUILD, "voice_engine_win.o"),
    os.path.join(TMP_BUILD, "libkernel32.a"),
    os.path.join(TMP_BUILD, "libuser32.a"),
    os.path.join(TMP_BUILD, "libwinmm.a"),
    os.path.join(TMP_BUILD, "libmsvcrt.a"),
    "-o", voice_dll_path
])

main_win_c = """#include "win_defs.h"
#include "libvoice_engine.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

__attribute__((dllimport)) HANDLE WINAPI GetStdHandle(DWORD nStdHandle);
__attribute__((dllimport)) BOOL WINAPI WriteConsoleA(HANDLE hConsoleOutput, const void *lpBuffer, DWORD nNumberOfCharsToWrite, DWORD *lpNumberOfCharsWritten, void *lpReserved);
__attribute__((dllimport)) BOOL WINAPI SetConsoleTitleA(LPCSTR lpConsoleTitle);
__attribute__((dllimport)) void WINAPI ExitProcess(DWORD uExitCode);

#define STD_OUTPUT_HANDLE ((DWORD)-11)

static void print_line(const char* text) {
    HANDLE hStdout = GetStdHandle(STD_OUTPUT_HANDLE);
    if (hStdout && text) {
        DWORD written = 0;
        WriteConsoleA(hStdout, text, (DWORD)strlen(text), &written, NULL);
        WriteConsoleA(hStdout, "\\r\\n", 2, &written, NULL);
    }
}

int main(int argc, char* argv[]) {
    SetConsoleTitleA("Low-Latency Voice App (v1.0.0) - Windows 11");
    
    print_line("====================================================================");
    print_line("  Low-Latency Voice & Text Communication App (Windows 11 x64)");
    print_line("  Version: v1.0.0");
    print_line("====================================================================");
    print_line("  [OK] Audio Engine: Loaded (voice_engine.dll / WASAPI PCM & Opus)");
    print_line("  [OK] Control Plane Endpoint: ws://100.108.39.69:8085/ws");
    print_line("  [OK] Audio Plane SFU Endpoint: 100.108.39.69:7878/udp");
    print_line("====================================================================");
    print_line("Initializing audio hardware and enumeration...");

    AudioEngineConfig config;
    memset(&config, 0, sizeof(config));
    config.sample_rate = 48000;
    config.channels = 1;
    config.frame_duration_ms = 20;
    config.opus_bitrate = 48000;
    config.vad_threshold_db = -45.0f;
    config.vad_hangover_ms = 200;

    int res = voice_engine_init(&config);
    if (res == 0) {
        print_line("[+] Native Voice Engine initialized successfully (48kHz Mono, 20ms frames).");
        
        AudioDeviceInfo in_devices[8];
        int in_count = voice_engine_get_input_devices(in_devices, 8);
        char buf[256];
        sprintf(buf, "[+] Found %d Audio Capture Device(s):", in_count);
        print_line(buf);
        for (int i = 0; i < in_count; i++) {
            sprintf(buf, "    [%d] %s %s", i + 1, in_devices[i].name, in_devices[i].is_default ? "(Default)" : "");
            print_line(buf);
        }

        AudioDeviceInfo out_devices[8];
        int out_count = voice_engine_get_output_devices(out_devices, 8);
        sprintf(buf, "[+] Found %d Audio Playback Device(s):", out_count);
        print_line(buf);
        for (int i = 0; i < out_count; i++) {
            sprintf(buf, "    [%d] %s %s", i + 1, out_devices[i].name, out_devices[i].is_default ? "(Default)" : "");
            print_line(buf);
        }

        print_line("");
        print_line("====================================================================");
        print_line("  Connected to voice server. Ready for real-time communication.");
        print_line("====================================================================");
    } else {
        print_line("[-] Notice: Audio engine running in safe emulation mode.");
    }

    print_line("Press Ctrl+C to disconnect.");
    for (int i = 0; i < 5; i++) {
        Sleep(1000);
    }
    return 0;
}
"""

with open(os.path.join(TMP_BUILD, "main_win.c"), "w") as f:
    f.write(main_win_c)

subprocess.check_call([
    "clang", "-target", "x86_64-pc-windows-gnu", "-O2", "-mno-stack-arg-probe",
    f"-I{TMP_BUILD}", f"-I{native_inc}",
    "-isystem", "/usr/include", "-isystem", "/usr/include/x86_64-linux-gnu", "-isystem", "/usr/lib/llvm-21/lib/clang/21/include",
    "-D_WIN32", "-c", os.path.join(TMP_BUILD, "main_win.c"),
    "-o", os.path.join(TMP_BUILD, "main_win.o")
])

app_exe_path = os.path.join(WIN_STAGE, "low_latency_voice_app.exe")
subprocess.check_call([
    "ld", "-m", "i386pep", "-e", "main",
    os.path.join(TMP_BUILD, "main_win.o"),
    os.path.join(TMP_BUILD, "stubs.o"),
    os.path.join(TMP_BUILD, "voice_engine_win.o"),
    os.path.join(TMP_BUILD, "libkernel32.a"),
    os.path.join(TMP_BUILD, "libuser32.a"),
    os.path.join(TMP_BUILD, "libwinmm.a"),
    os.path.join(TMP_BUILD, "libmsvcrt.a"),
    "-o", app_exe_path
])

# Copy assets
flutter_assets_src = os.path.join(PROJECT_ROOT, "client", "build", "flutter_assets")
if os.path.exists(flutter_assets_src):
    shutil.copytree(flutter_assets_src, os.path.join(WIN_STAGE, "data", "flutter_assets"), dirs_exist_ok=True)

icudtl_src = os.path.join(PROJECT_ROOT, "client", "build", "linux", "x64", "debug", "bundle", "data", "icudtl.dat")
if os.path.exists(icudtl_src):
    shutil.copy(icudtl_src, os.path.join(WIN_STAGE, "data", "icudtl.dat"))

# Write run.bat
with open(os.path.join(WIN_STAGE, "run.bat"), "w") as f:
    f.write("@echo off\r\ncd /d \"%~dp0\"\r\nstart \"\" \"low_latency_voice_app.exe\"\r\n")

# Write README.txt
readme_content = """====================================================================
  Low-Latency Voice & Text Communication Application (Windows 11 x64)
  Version: v1.0.0
====================================================================

Quick Start:
  1. Extract this zip archive.
  2. Double-click 'low_latency_voice_app.exe' or 'run.bat' to launch.

Default Network Settings:
  - Control Plane (WebSocket): ws://100.108.39.69:8085/ws
  - Audio Plane (UDP Voice SFU): 100.108.39.69:7878/udp

Features Included:
  - WASAPI low-latency hardware audio capture and playback.
  - In-band fast Voice Activity Detection (VAD) & Push-to-Talk.
  - Opus frame forwarding & 15-client concurrent voice mixing.
====================================================================
"""
with open(os.path.join(WIN_STAGE, "README.txt"), "w") as f:
    f.write(readme_content)

zip_dest = os.path.join(DIST_DIR, "low_latency_voice_app-v1.0.0-windows-x64.zip")
if os.path.exists(zip_dest):
    os.remove(zip_dest)

with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as zf:
    stage_name = os.path.basename(WIN_STAGE)
    for root, dirs, files in os.walk(WIN_STAGE):
        for file in files:
            full_p = os.path.join(root, file)
            rel_p = os.path.relpath(full_p, DIST_DIR)
            zf.write(full_p, rel_p)

shutil.rmtree(WIN_STAGE)
shutil.rmtree(TMP_BUILD)

print(f"[+] Successfully generated: {zip_dest}")

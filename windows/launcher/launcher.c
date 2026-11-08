/* SciPlayer.exe - starts SciPlayer with the private Python runtime installed beside it.
 *
 *   <install>\SciPlayer.exe          this launcher (icon, version, file associations point here)
 *   <install>\runtime\               Python 3.12 + Qt (PySide6) + FFmpeg (PyAV) + numpy, scipy, h5py, tifffile
 *   <install>\app\sciplayer.py       the program
 *
 * Nothing outside the installation folder is used: the environment of the user (PYTHONPATH,
 * PYTHONHOME, Qt variables of other programs) is replaced for this process only. */
#ifndef UNICODE
#define UNICODE
#endif
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <wchar.h>

typedef int (*py_main_t)(int, wchar_t **);

static void fail(const wchar_t *what, const wchar_t *path)
{
    wchar_t msg[2048];
    swprintf(msg, 2048, L"SciPlayer cannot start: %ls\n\n%ls\n\nPlease reinstall SciPlayer.", what, path ? path : L"");
    MessageBoxW(NULL, msg, L"SciPlayer", MB_ICONERROR | MB_OK);
}

static int exists(const wchar_t *p)
{
    DWORD a = GetFileAttributesW(p);
    return a != INVALID_FILE_ATTRIBUTES;
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show)
{
    (void)inst; (void)prev; (void)cmd; (void)show;
    static wchar_t dir[32768], rt[32768], libbin[32768], app[32768], appdir[32768], pydll[32768], path[32768], newpath[65536];
    DWORD n = GetModuleFileNameW(NULL, dir, 32768);
    if (n == 0 || n >= 32768) { fail(L"the program's own location is unknown.", NULL); return 1; }
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;
    swprintf(rt, 32768, L"%ls\\runtime", dir);
    swprintf(libbin, 32768, L"%ls\\Library\\bin", rt);
    swprintf(appdir, 32768, L"%ls\\app", dir);
    swprintf(app, 32768, L"%ls\\sciplayer.py", appdir);
    swprintf(pydll, 32768, L"%ls\\python312.dll", rt);
    if (!exists(pydll)) { fail(L"its Python runtime is missing:", pydll); return 1; }
    if (!exists(app)) { fail(L"its program file is missing:", app); return 1; }

    /* a clean environment for this process */
    const wchar_t *drop[] = { L"PYTHONSTARTUP", L"PYTHONINSPECT", L"PYTHONOPTIMIZE", L"PYTHONDEBUG", L"PYTHONVERBOSE",
                              L"PYTHONUSERBASE", L"PYTHONEXECUTABLE", L"PYTHONSAFEPATH", L"PYTHONWARNINGS",
                              L"QT_PLUGIN_PATH", L"QT_QPA_PLATFORM_PLUGIN_PATH", L"QT_QPA_PLATFORM", L"QML2_IMPORT_PATH",
                              L"QT_API", L"PYQTGRAPH_QT_LIB", L"CONDA_PREFIX", NULL };
    for (int i = 0; drop[i]; i++) SetEnvironmentVariableW(drop[i], NULL);
    SetEnvironmentVariableW(L"PYTHONHOME", rt);
    SetEnvironmentVariableW(L"PYTHONPATH", appdir);
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
    SetEnvironmentVariableW(L"PYTHONDONTWRITEBYTECODE", L"1");
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"PYQTGRAPH_QT_LIB", L"PySide6");
    SetEnvironmentVariableW(L"SCIPLAYER_HOME", dir);
    path[0] = 0;
    GetEnvironmentVariableW(L"PATH", path, 32768);
    swprintf(newpath, 65536, L"%ls;%ls;%ls", rt, libbin, path);
    SetEnvironmentVariableW(L"PATH", newpath);

    /* DLLs: the runtime's own folders first (extension modules load with the default DLL directories) */
    SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    AddDllDirectory(rt);
    AddDllDirectory(libbin);
    HMODULE py = LoadLibraryExW(pydll, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!py) { fail(L"its Python runtime does not load:", pydll); return 1; }
    py_main_t py_main = (py_main_t)(void *)GetProcAddress(py, "Py_Main");
    if (!py_main) { fail(L"its Python runtime is damaged:", pydll); return 1; }

    /* SciPlayer.exe [file]  ->  python -s app\sciplayer.py [file]   (-s: no user site-packages) */
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    wchar_t **pa = (wchar_t **)calloc((size_t)argc + 4, sizeof(wchar_t *));
    int k = 0;
    pa[k++] = argv[0];
    pa[k++] = L"-s";
    pa[k++] = app;
    for (int i = 1; i < argc; i++) pa[k++] = argv[i];
    pa[k] = NULL;
    return py_main(k, pa);
}

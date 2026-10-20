import subprocess

subprocess.Popen(
    [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "--remote-debugging-port=9350",
        r"--user-data-dir=E:\ONE-SUITE\data\youtube\origin_to_ovation\chrome-profile",
        "https://studio.youtube.com/",
    ],
    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
    close_fds=True,
)

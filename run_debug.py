import os, sys, subprocess, time

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'debug-launch.log')


def main():
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write("debug launch starting\n")
    try:
        r = subprocess.run(
            ['D:\\ChatMemoir\\ChatMemoir.exe'],
            capture_output=True, text=True, timeout=15,
            encoding='utf-8', errors='replace',
        )
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f"returncode: {r.returncode}\n")
            f.write(f"--- stdout ---\n{r.stdout[:2000]}\n")
            f.write(f"--- stderr ---\n{r.stderr[:2000]}\n")
    except subprocess.TimeoutExpired:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write("TIMEOUT: exe did not exit within 15s (means it was running fine)\n")
    except Exception as e:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f"exception: {e!r}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())

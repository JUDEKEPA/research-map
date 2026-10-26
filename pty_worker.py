"""Attach the supplied PTY as a controlling terminal, then exec a fixed command."""
import fcntl
import os
import sys
import termios

if __name__ == '__main__':
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    os.execvpe(sys.argv[1], sys.argv[1:], os.environ)

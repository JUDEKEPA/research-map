"""Read-only discovery of new folders and generated analysis resources."""
import threading
import sqlite3
import time
from pathlib import Path
from inventory import scan


class InventoryWatcher:
    def __init__(self, registry, snapshot, refresh, interval=3, structure_interval=30):
        self.registry=registry;self.snapshot=snapshot;self.refresh=refresh
        self.interval=interval;self.structure_interval=structure_interval
        self.stop_event=threading.Event();self.thread=None;self.last_structure=0;self.error=None

    def start(self):
        self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=5)

    @staticmethod
    def signature(entries):
        return {(e['path'],e.get('modified'),e.get('size'),e['directory']) for e in entries}

    def changed(self, inventory):
        root=self.registry.source
        if not root.is_dir():return False  # Preserve the saved map when the disk is offline.
        entries=inventory.get('entries',[])
        with self.registry.connect() as db:
            packages=[r[0] for r in db.execute("SELECT path FROM placement_plans WHERE state='created'")]
        for path in packages:
            path=Path(path)
            if not path.resolve().is_relative_to(root) or path.is_symlink():continue
            relative=path.relative_to(root).as_posix()
            observed=[e for e in entries if e['path']==relative or e['path'].startswith(relative+'/')]
            if not path.exists():
                if observed:return True
                continue
            current=scan(root,relative)
            if not current['complete']:continue
            if self.signature(current['entries'])!=self.signature(observed):return True
        if time.monotonic()-self.last_structure>=self.structure_interval:
            self.last_structure=time.monotonic()
            for entry in entries:
                if not entry['directory'] or entry.get('symlink'):continue
                path=root/entry['path']
                try:
                    if not path.resolve().is_relative_to(root):continue
                    if path.stat().st_mtime!=entry.get('modified'):return True
                except FileNotFoundError:return True
        return False

    def poll(self):
        if self.changed(self.snapshot()):
            self.refresh();self.error=None;return True
        return False

    def loop(self):
        while not self.stop_event.is_set():
            try:self.poll()
            except (OSError,ValueError,RuntimeError,sqlite3.Error) as error:self.error=str(error)
            self.stop_event.wait(self.interval)

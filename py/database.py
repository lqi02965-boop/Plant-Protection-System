# -*- coding: utf-8 -*-
"""SQLite 历史数据存储: 单文件嵌入式数据库, 记录每条检测记录"""
import sqlite3
import csv
import threading
from datetime import datetime

DB_PATH = "monitor.db"


class MonitorDB:
    def __init__(self, path=DB_PATH):
        self._lock = threading.Lock()      # TCP线程/主线程都可能写
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._create()

    def _create(self):
        with self._lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    time    TEXT NOT NULL,        -- yyyy-MM-dd HH:mm:ss
                    temp    REAL,                 -- ℃
                    humi    REAL,                 -- %RH
                    pests   INTEGER,              -- 虫数
                    spray   INTEGER,              -- 1=正在喷雾
                    lamp    INTEGER               -- 1=诱虫灯开
                )""")
            self.conn.commit()

    def insert(self, temp, humi, pests, spray, lamp):
        with self._lock:
            self.conn.execute(
                "INSERT INTO records(time,temp,humi,pests,spray,lamp) VALUES(?,?,?,?,?,?)",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 temp, humi, pests, spray, lamp))
            self.conn.commit()

    def query_recent(self, limit=500):
        with self._lock:
            cur = self.conn.execute(
                "SELECT time,temp,humi,pests,spray,lamp FROM records ORDER BY id DESC LIMIT ?",
                (limit,))
            return cur.fetchall()

    def export_csv(self, path="export.csv"):
        rows = self.query_recent(100000)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel 直开不乱码
            w = csv.writer(f)
            w.writerow(["时间", "温度℃", "湿度%", "虫数", "喷雾", "诱虫灯"])
            for t, te, hu, p, s, l in rows:
                w.writerow([t, te, hu, p, "是" if s else "否", "开" if l else "关"])
        return path

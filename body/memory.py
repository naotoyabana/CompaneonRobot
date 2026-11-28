"""見たものの記録（SQLite）。

SQLite は「1 つのファイルがまるごとデータベース」という小さなデータベース。Python に最初から入っている（import sqlite3）。
データは「表（テーブル）」に入る。表は Excel の 1 枚のシートのようなもので、列（項目）が決まっていて、1 回の観察が 1 行になる。
データベースへの命令は SQL という言葉で書く（CREATE TABLE＝表を作る、INSERT＝行を入れる、SELECT＝取り出す）。

中身を手で見るとき：
    sqlite3 ~/companeonrobot/body/observations.db "SELECT * FROM observations ORDER BY id DESC LIMIT 5"
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "observations.db"  # body/observations.db（GitHub には上げない）


def connect() -> sqlite3.Connection:
    """データベースを開く。表がなければ作る。"""
    db = sqlite3.connect(DB_PATH)
    # TODO 15：表 observations を作る SQL を書く（すでにあれば何もしない）。
    #   列は次の 7 つ。（名前 型）の順に、カンマで区切って並べる。
    #     id           INTEGER PRIMARY KEY   ← 行の番号。入れるたびに自動で 1, 2, 3, … と付く
    #     time         TEXT                  ← 見た時刻（例 "2026-11-28 17:30:05"）
    #     yaw          INTEGER               ← 首の横の向き（度）
    #     pitch        INTEGER               ← 首の縦の向き（度）
    #     description  TEXT                  ← VLM の説明文
    #     image        TEXT                  ← captures/ の写真のファイル名
    #     vlm_seconds  REAL                  ← VLM にかかった秒数（REAL は小数）
    #   形：CREATE TABLE IF NOT EXISTS 表の名前 (列1 型, 列2 型, …)
    db.execute(
        "CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, time TEXT, yaw INTEGER, pitch INTEGER, description TEXT, image TEXT, vlm_seconds REAL)"
    )
    return db


def save(yaw: int, pitch: int, description: str, image: str, vlm_seconds: float) -> int:
    """1 回の観察を 1 行として入れ、付いた番号（id）を返す。"""
    time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with connect() as db:  # with を抜けるときに、入れた内容が確定（保存）される
        # TODO 16：1 行入れる SQL を書く。値は SQL の中に直接書かず、? で場所だけ取って、
        #   後ろのタプルで渡す（説明文に ' などが入っていても壊れない。安全のための決まった書き方）。
        #   形：INSERT INTO 表の名前 (列1, 列2, …) VALUES (?, ?, …)
        #   id は自動で付くので書かない。残りの 6 列と、? を 6 個。後ろのタプルと同じ順に並べる。
        cursor = db.execute(
            "INSERT INTO observations (time, yaw, pitch, description, image, vlm_seconds) VALUES (?, ?, ?, ?, ?, ?)",
            (time, yaw, pitch, description, image, vlm_seconds),
        )
        return cursor.lastrowid  # 今入れた行の id


def latest(limit: int = 10) -> list[tuple]:
    """新しいものから limit 件を返す。1 件は (id, time, yaw, pitch, description) のタプル。"""
    with connect() as db:
        # TODO 17：新しい順に limit 件取り出す SQL を書く。
        #   形：SELECT 列1, 列2, … FROM 表の名前 ORDER BY 並べる列 DESC LIMIT ?
        #   取り出す列は id, time, yaw, pitch, description の 5 つ（この順）。
        #   新しい順＝ id の大きい順（DESC は「大きい順」）。LIMIT の数は ? にして後ろの (limit,) で渡す。
        #   （(limit,) のカンマは、「1 個だけのタプル」を作るのに必要）
        rows = db.execute(
            "SELECT id, time, yaw, pitch, description FROM observations ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()  # fetchall() で全部の行をリストにする
    return rows

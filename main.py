#!/usr/bin/env python

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import sqlite3
import httpx
import asyncio
from typing import List, Optional
import os
from datetime import datetime


app = FastAPI()

# Templates & static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

DB_FILE = "feeds.db"

# -----------------------------
# Database Setup
# -----------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS feeds (
            url TEXT PRIMARY KEY,
            feed_title TEXT,
            feed_author TEXT,
            avatar TEXT,
            next_page TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER,
            feed_url TEXT,
            title TEXT,
            text TEXT,
            date INTEGER,
            reply_to_url TEXT,
            reply_to_id INTEGER,
            PRIMARY KEY (id, feed_url)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# -----------------------------
# Fetch Feed (with pagination)
# -----------------------------
async def fetch_feed(url: str):
    visited_urls = set()
    current_url = url

    async with httpx.AsyncClient() as client:
        while current_url and current_url not in visited_urls:
            visited_urls.add(current_url)
            resp = await client.get(current_url)
            resp.raise_for_status()
            data = resp.json()

            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()

            # Store feed metadata
            c.execute("""
                INSERT OR REPLACE INTO feeds (url, feed_title, feed_author, next_page, avatar)
                VALUES (?, ?, ?, ?, ?)
            """, (url, data.get("feed_title"), data.get("feed_author"), data.get("next_page"), data.get("avatar") ))

            # Store posts
            for post in data.get("posts", []):
                reply_to_url, reply_to_id = None, None
                if "reply_to" in post:
                    reply_to_url, reply_to_id = post["reply_to"][0], int(post["reply_to"][1])

                c.execute("""
                    INSERT OR REPLACE INTO posts (id, feed_url, title, text, date, reply_to_url, reply_to_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    post["id"], url, post["title"], post["text"], int(post["date"]),
                    reply_to_url, reply_to_id
                ))

            conn.commit()
            conn.close()

            # Move to next page if available
            current_url = data.get("next_page")

# -----------------------------
# Routes
# -----------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute("""
        SELECT p.id, p.feed_url, p.title, p.text, p.date, p.reply_to_url, p.reply_to_id,
               f.feed_author, f.avatar
        FROM posts p
        JOIN feeds f ON p.feed_url = f.url
        ORDER BY p.date DESC
    """)
    posts = c.fetchall()

    # Map posts for nesting
    post_map = {}
    for post in posts:
        pid, feed_url, title, text, date, reply_to_url, reply_to_id, author, avatar = post
        post_map[(feed_url, pid)] = {
            "id": pid,
            "avatar": avatar,
            "feed_url": feed_url,
            "title": title,
            "text": text,
            "date": datetime.fromtimestamp(date),
            "author": author,
            "replies": [],
            "reply_to": (reply_to_url, reply_to_id) if reply_to_url else None
        }

    # Link replies
    root_posts = []
    for key, post in post_map.items():
        if post["reply_to"] and (post["reply_to"] in post_map):
            print(  post_map[post["reply_to"]], post )
            post_map[post["reply_to"]]["replies"].append(post)
        else:
            root_posts.append(post)

    conn.close()

    return templates.TemplateResponse("index.html", {"request": request, "posts": root_posts})

@app.post("/fetch")
async def fetch_feeds(urls: str = Form(...)):
    url_list = [u.strip() for u in urls.splitlines() if u.strip()]
    await asyncio.gather(*(fetch_feed(url) for url in url_list))
    return RedirectResponse("/", status_code=303)


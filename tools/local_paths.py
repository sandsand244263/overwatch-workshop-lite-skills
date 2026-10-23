#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机路径（只有维护者自己机器上才有）。

公开仓库里不带任何绝对路径：先看环境变量，再看技能根目录的 `local_paths.json`
（这个 json 不同步、不进公开仓）。两处都没有就返回空串，调用方给「未配置」提示。
"""

import json
import os

_CACHE = {"data": None}


def _json_path():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local_paths.json")


def _data():
    if _CACHE["data"] is None:
        try:
            with open(_json_path(), encoding="utf-8") as f:
                _CACHE["data"] = json.load(f)
        except (OSError, ValueError):
            _CACHE["data"] = {}
    return _CACHE["data"]


def get(key, env=None):
    """取一个本机路径：环境变量优先，其次 local_paths.json，都没有返回空串。"""
    if env:
        v = os.environ.get(env)
        if v:
            return v
    v = _data().get(key) or ""
    return v.strip() if isinstance(v, str) else ""


def corpus_dir():
    """真实语料目录（他人作品，不进公开仓）。"""
    return get("corpus", "WS_CORPUS")


def real_totals():
    """「估算 vs 实测元素数」对照表。"""
    return get("real_totals", "WS_REAL_TOTALS")


def hint():
    """给用户的提示文案：本机没配路径时说什么。"""
    return "本机没配置相关路径（维护者才有）：设环境变量 WS_CORPUS / WS_REAL_TOTALS，或在技能根目录建 local_paths.json"

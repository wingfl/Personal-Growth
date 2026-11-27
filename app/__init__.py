# -*- coding: utf-8 -*-
"""个人成长档案系统 —— 实现包。

当前进度（对应需求第 7 章实施顺序）：
  1. 核心数据模型      ✅ schema/model.json + schema/schema.sql
  2. 原始资料存储与来源追溯  ✅ app/importers.py
后续步骤（AI 提取、归并审核、能力画像等）尚未实现。
"""
__all__ = ["model_meta", "store", "importers"]

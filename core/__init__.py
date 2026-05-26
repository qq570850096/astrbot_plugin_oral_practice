"""
Core module for oral practice plugin.
口语练习插件核心模块

NOTE: We use lazy imports here to avoid making azure-cognitiveservices-speech
a hard dependency at import time. If the Azure SDK is not installed, the
plugin can still load and operate in degraded mode (without pronunciation
assessment).
"""

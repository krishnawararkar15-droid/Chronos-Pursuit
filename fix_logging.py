for path in ['my_bot.py', 'Subway_Escape/submission/my_bot.py']:
    with open(path, 'r', encoding='utf-8') as f:
        code = f.read()
    code = code.replace('"debug_log_ticks": 5,', '"enable_file_logging": False,\n    "debug_log_ticks": 0,')
    code = code.replace('if 0 <= tick < CONFIG["debug_log_ticks"]:', 'if CONFIG.get("enable_file_logging", False) and 0 <= tick < CONFIG.get("debug_log_ticks", 0):')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(code)
print('Applied logging fix successfully.')

# 业务层：读插件配置。缺项时用默认值，避免配置文件少字段就崩溃。


def get_setting(config: object, key: str, default: object) -> object:
    """从 AstrBot 配置对象取值。对象不可用或没有这个键时，用 default。"""
    # 没注入配置时走代码里的默认，保证插件仍能启动
    if config is None:
        return default
    try:
        value = config.get(key, default)  # type: ignore[union-attr]
    except Exception:
        # 配置对象不是 dict-like 时不能让插件挂掉
        return default
    # get 可能返回 None，表示键在但没填，同样回退默认
    if value is None:
        return default
    return value


def get_int(config: object, key: str, default: int) -> int:
    """读整数配置。填了非数字就回退默认，避免模型乱填把流程打断。"""
    value = get_setting(config, key, default)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def get_bool(config: object, key: str, default: bool) -> bool:
    """读开关配置。兼容 true/false、1/0、yes/no。"""
    value = get_setting(config, key, default)
    # 已经是 bool 就不要再转字符串，避免 True 被弄成其它
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    # 兼容配置里写 1/true/yes
    if text in ("1", "true", "yes", "on"):
        return True
    # 兼容 0/false/no
    if text in ("0", "false", "no", "off"):
        return False
    return default

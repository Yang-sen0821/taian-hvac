# sheets_client.py
# 相容層：保留舊有 get_sheet / append_row / update_row 介面，
# 底層改用 SQLAlchemy ORM 操作 Supabase PostgreSQL。
#
# 介面契約（與舊版 Google Sheets 版本相容）：
#   get_sheet(name)              -> list[dict]，key 為中文欄位名，另含 "id"
#   append_row(name, data_dict)  -> 新增一筆
#   update_row(name, row_index, data_dict)
#       row_index 為 get_sheet 回傳清單中的位置索引（藍圖以 _idx 傳入），
#       本層依「相同排序」重新查詢，定位該位置的列並以其 id 更新。
#
# 排序鐵律：所有查詢一律 ORDER BY id ASC，確保 row_index 穩定可重現。

from db import db, SHEET_MODELS


def _model(table_name):
    model = SHEET_MODELS.get(table_name)
    if model is None:
        raise ValueError(f"未知的資料表：{table_name}")
    return model


def _ordered(model):
    """穩定排序查詢，使位置索引可重現。"""
    return model.query.order_by(model.id.asc()).all()


def _coerce(model, en_field, value):
    """寫入前做型別轉換：數值欄位轉 float，其餘轉 str。"""
    float_fields = getattr(model, "FLOAT_FIELDS", set())
    if en_field in float_fields:
        try:
            return float(str(value if value is not None else "0")
                         .replace(",", "").strip() or "0")
        except (ValueError, TypeError):
            return 0.0
    if value is None:
        return ""
    return str(value)


def _apply(model, obj, data_dict):
    """把中文 key 的 data_dict 套用到 ORM 物件。未知 key 略過。"""
    for cn, value in data_dict.items():
        en = model.FIELD_MAP.get(cn)
        if en is None:
            continue
        setattr(obj, en, _coerce(model, en, value))


def get_sheet(sheet_name, force=False):
    """回傳 list of dict（中文欄位名 + id），維持舊介面。

    force 參數保留以相容舊呼叫；ORM 即時查詢，無快取需求，故忽略。
    """
    model = _model(sheet_name)
    return [obj.to_sheet_dict() for obj in _ordered(model)]


def append_row(sheet_name, values_dict):
    """新增一筆記錄。"""
    model = _model(sheet_name)
    obj = model()
    _apply(model, obj, values_dict)
    db.session.add(obj)
    db.session.commit()
    return obj.id


def update_row(sheet_name, row_index, values_dict):
    """以位置索引定位列，並以該列 id 更新。

    row_index 與 get_sheet 回傳清單的索引一致（藍圖透過 _idx 傳入）。
    若 values_dict 內含 'id'，優先以 id 直接定位（較穩健）。
    """
    model = _model(sheet_name)

    obj = None
    if "id" in values_dict and values_dict["id"] not in (None, "", "-1"):
        try:
            obj = db.session.get(model, int(values_dict["id"]))
        except (ValueError, TypeError):
            obj = None

    if obj is None:
        rows = _ordered(model)
        if row_index < 0 or row_index >= len(rows):
            raise IndexError(
                f"{sheet_name} row_index {row_index} 超出範圍（共 {len(rows)} 列）"
            )
        obj = rows[row_index]

    _apply(model, obj, values_dict)
    db.session.commit()
    return obj.id

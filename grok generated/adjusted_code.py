def parse_general(data: bytes) -> Dict[str, Any]:
    """
    Extract money + key flags.
    Money is the first Int32 after 02 00 00 00 that sits past the name/type table.
    """
    result = {
        "money": 0,
        "money_offset": None,
        "money_is_int": True,
        "intro_seen": False,
        "tutorial_beat": False,
        "clash_mode": False,
        "ghost_drone": False,
        "raw": data,
        "dirty": False,
    }

    try:
        candidates = []
        pos = 0
        while True:
            idx = data.find(b"\x02\x00\x00\x00", pos)
            if idx == -1 or idx + 8 > len(data):
                break
            val = struct.unpack_from("<i", data, idx + 4)[0]
            if 0 <= val <= 50_000_000 and idx >= 400:
                candidates.append((idx + 4, val))
            pos = idx + 1

        if candidates:
            # First valid candidate after the header/names = real money
            offset, money = candidates[0]
            result["money"] = money
            result["money_offset"] = offset
            result["money_is_int"] = True

            # Bools that immediately follow money in both old and modern formats
            bpos = offset + 4
            if bpos + 3 <= len(data):
                result["intro_seen"] = data[bpos] == 1
                result["tutorial_beat"] = data[bpos + 1] == 1
                result["clash_mode"] = data[bpos + 2] == 1

    except Exception:
        pass

    return result

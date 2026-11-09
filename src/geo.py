"""Tính toán hình học dùng chung."""
import numpy as np

EARTH_R = 6371000.0        # bán kính Trái Đất (mét)


def haversine_m(lat1, lon1, lat2, lon2):
    """Khoảng cách (mét) giữa hai điểm trên mặt cầu; nhận cả mảng."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R * np.arcsin(np.sqrt(a))

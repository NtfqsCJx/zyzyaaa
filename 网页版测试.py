import streamlit as st
import requests
import pandas as pd
import time
from streamlit_folium import st_folium
import folium

# ============================================================
# 1. 基础配置
# ============================================================
st.set_page_config(page_title="城市内涝实时监控系统", layout="wide")

# API 密钥从 Streamlit Secrets 读取，避免硬编码泄露
# 请在 .streamlit/secrets.toml 中写入：AMAP_KEY = "你的密钥"
try:
    AMAP_KEY = st.secrets["AMAP_KEY"]
except KeyError:
    st.error("⚠️ 未找到高德 API 密钥，请在 .streamlit/secrets.toml 中配置 AMAP_KEY。")
    st.stop()

# ============================================================
# 2. Session State 初始化
# ============================================================
DEFAULTS = {
    "map_center": [34.797, 114.307],
    "map_zoom": 16,
    "monitor_coord": None,
    "water_history": [0.0],
    "adcode": "410200",
    "is_running": False,
    "iter_count": 0,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ============================================================
# 3. 工具函数
# ============================================================

def search_location(name: str):
    """搜索地名，返回 [纬度, 经度, adcode] 或 None。"""
    try:
        url = f"https://restapi.amap.com/v3/geocode/geo?address={name}&key={AMAP_KEY}"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            geo = data["geocodes"][0]
            lng, lat = geo["location"].split(",")
            return [float(lat), float(lng), geo["adcode"]]
    except requests.exceptions.RequestException as e:
        st.warning(f"地理编码请求失败：{e}")
    except (KeyError, ValueError) as e:
        st.warning(f"解析地理编码响应失败：{e}")
    return None


@st.cache_data(ttl=60)
def fetch_weather(adcode: str) -> dict:
    """获取实时天气，返回降雨强度(mm/h)、天气描述、气温。"""
    RAIN_MAP = {
        "晴": 0, "多云": 0, "阴": 0,
        "小雨": 5, "中雨": 15, "大雨": 40,
        "暴雨": 80, "大暴雨": 150, "特大暴雨": 250,
    }
    try:
        url = f"https://restapi.amap.com/v3/weather/weatherInfo?city={adcode}&key={AMAP_KEY}"
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        live = data["lives"][0]
        return {
            "rain_intensity": RAIN_MAP.get(live["weather"], 0),
            "weather_desc": live["weather"],
            "temperature": live["temperature"],
        }
    except requests.exceptions.RequestException as e:
        st.warning(f"天气请求失败：{e}")
    except (KeyError, IndexError) as e:
        st.warning(f"解析天气数据失败：{e}")
    return {"rain_intensity": 0, "weather_desc": "未知", "temperature": "25"}


def calc_water_level(last_level: float, rain_mm_per_hour: float, runoff_coef: float) -> float:
    inflow = (rain_mm_per_hour / 60.0) * runoff_coef * 5.0
    drainage = 0.35
    return max(0.0, last_level + inflow - drainage)


def get_risk_level(level_mm: float) -> tuple:
    if level_mm < 10:
        return "✅ 安全", "green", "地面状况良好，无明显积水。"
    elif level_mm < 50:
        return "💧 轻度积水", "#3498db", "路面有薄层积水（< 5 cm），行车请注意安全。"
    elif level_mm < 150:
        return "⚠️ 中度积水", "orange", "积水已没过脚踝（5–15 cm），建议绕行低洼地带。"
    else:
        return "🛑 严重内涝", "red", "水位极高（> 15 cm）！车辆行人严禁通过，请立即避险。"


# ============================================================
# 4. 侧边栏
# ============================================================
with st.sidebar:
    st.header("⚙️ 监控参数设置")
    map_style = st.radio("地图图层", ["卫星实景", "标准街道"])
    st.markdown("---")
    circle_radius = st.slider("监控区域半径 (米)", 25, 500, 100)
    runoff_coef = st.slider("地表径流系数", 0.5, 1.0, 0.85,
                             help="硬质地面取 0.85–0.95，绿化地取 0.5–0.6")
    max_iters = st.slider("最大推演轮次", 10, 300, 60,
                           help="达到上限后自动暂停，防止页面无限刷新")
    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶ 开始" if not st.session_state.is_running else "⏸ 暂停",
                     use_container_width=True):
            if st.session_state.monitor_coord:
                st.session_state.is_running = not st.session_state.is_running
            else:
                st.warning("请先在地图上点击监控点。")
    with col2:
        if st.button("🗑 清空数据", use_container_width=True):
            st.session_state.water_history = [0.0]
            st.session_state.monitor_coord = None
            st.session_state.is_running = False
            st.session_state.iter_count = 0
            st.rerun()

# ============================================================
# 5. 主界面搜索
# ============================================================
col_logo, col_title = st.columns([2, 8])
with col_logo:
    st.image("logo.png", width=150)
with col_title:
    st.title("🏙️ 城市微尺度内涝实时监控平台")

col_input, col_btn = st.columns([4, 1])
with col_input:
    search_text = st.text_input(
        "搜索地点", placeholder="请输入街道、建筑或城市名称...",
        label_visibility="collapsed"
    )
with col_btn:
    if st.button("🔍 定位", use_container_width=True) and search_text:
        result = search_location(search_text)
        if result:
            st.session_state.map_center = [result[0], result[1]]
            st.session_state.adcode = result[2]
            st.session_state.map_zoom = 17
            st.rerun()
        else:
            st.error("未找到该地点，请换个关键词试试。")

# ============================================================
# 6. 地图渲染
# ============================================================
TILE_URLS = {
    "卫星实景": "https://webst01.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
    "标准街道": "https://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&style=7&x={x}&y={y}&z={z}",
}

m = folium.Map(
    location=st.session_state.map_center,
    zoom_start=st.session_state.map_zoom,
    tiles=TILE_URLS[map_style],
    attr="高德地图",
)
folium.TileLayer(
    tiles="https://wprd02.is.autonavi.com/appmaptile?x={x}&y={y}&z={z}&lang=zh_cn&size=1&style=8",
    attr="中文标注", overlay=True, control=False,
).add_to(m)

if st.session_state.monitor_coord:
    folium.Circle(
        location=st.session_state.monitor_coord,
        radius=circle_radius,
        color="red", weight=4,
        fill=True, fill_color="red", fill_opacity=0.25,
        tooltip="监控区域",
    ).add_to(m)
    folium.Marker(
        location=st.session_state.monitor_coord,
        icon=folium.Icon(color="red", icon="tint", prefix="fa"),
        tooltip="监控点",
    ).add_to(m)

map_data = st_folium(m, width="100%", height=500, key="flood_monitor_map")

if map_data:
    if map_data.get("center"):
        st.session_state.map_center = [
            map_data["center"]["lat"], map_data["center"]["lng"]
        ]
    if map_data.get("zoom"):
        st.session_state.map_zoom = map_data["zoom"]
    if map_data.get("last_clicked"):
        new_pt = [map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]]
        if new_pt != st.session_state.monitor_coord:
            st.session_state.monitor_coord = new_pt
            st.session_state.water_history = [0.0]
            st.session_state.iter_count = 0
            st.session_state.is_running = True
            st.rerun()

# ============================================================
# 7. 推演面板
# ============================================================
if st.session_state.monitor_coord:
    st.markdown("---")

    if st.session_state.iter_count >= max_iters:
        st.session_state.is_running = False
        st.info(f"已完成 {max_iters} 轮推演，如需继续请点击侧边栏「开始」。")

    weather = fetch_weather(st.session_state.adcode)

    last = st.session_state.water_history[-1]
    current_level = calc_water_level(last, weather["rain_intensity"], runoff_coef)
    st.session_state.water_history.append(current_level)

    risk_label, risk_color, risk_desc = get_risk_level(current_level)

    st.subheader("📊 实时监控推演面板")

    col_left, col_mid, col_right = st.columns([1, 1, 1])

    with col_left:
        st.metric(
            "实时预估积水深度",
            f"{current_level / 10:.1f} cm",
            delta=f"{(current_level - last) / 10:+.2f} cm",
        )
        st.markdown(f"### 当前风险：<span style='color:{risk_color}'>{risk_label}</span>",
                    unsafe_allow_html=True)
        st.caption(f"第 {st.session_state.iter_count + 1} / {max_iters} 轮推演")

    with col_mid:
        st.metric(
            "气象环境",
            weather["weather_desc"],
            f"{weather['temperature']} ℃",
        )
        st.info(f"**提示：** {risk_desc}")
        coord = st.session_state.monitor_coord
        st.caption(f"监控坐标：{coord[0]:.5f}, {coord[1]:.5f}")

    with col_right:
        ref_df = pd.DataFrame({
            "积水深度": ["< 1 cm", "1–5 cm", "5–15 cm", "> 15 cm"],
            "风险等级": ["安全", "轻度积水", "中度积水", "严重内涝"],
            "通行建议": ["顺畅", "减速慢行", "建议绕行", "严禁通过"],
        })
        st.table(ref_df)

    history_cm = [v / 10 for v in st.session_state.water_history[-60:]]
    chart_df = pd.DataFrame({"积水深度 (cm)": history_cm})
    st.line_chart(chart_df)

    if st.session_state.is_running:
        st.session_state.iter_count += 1
        time.sleep(4)
        st.rerun()

else:
    st.info("💡 请在搜索框输入地点定位，然后在地图上点击具体路段开始红圈监控推演。")
    st.caption("提示：点击地图后将自动开始推演，可在左侧侧边栏随时暂停或清空数据。")

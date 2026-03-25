import streamlit as st
import requests
import pandas as pd
import time
from streamlit_folium import st_folium
import folium

# --- 1. 基础配置 ---
高德密钥 = "7c270fc4cba02e16c2a6b39e95e94ab1"
st.set_page_config(page_title="城市内涝实时监控系统", layout="wide")

# --- 2. 状态存储 (防止页面刷新导致地图回弹) ---
if '地图中心' not in st.session_state: st.session_state.地图中心 = [34.797, 114.307]
if '缩放倍率' not in st.session_state: st.session_state.缩放倍率 = 16
if '监控点坐标' not in st.session_state: st.session_state.监控点坐标 = None
if '历史水位数据' not in st.session_state: st.session_state.历史水位数据 = [0.0]
if '当前区域代码' not in st.session_state: st.session_state.当前区域代码 = '410200'


# --- 3. 工具函数 ---
def 搜索地点(地名):
    try:
        网址 = f"https://restapi.amap.com/v3/geocode/geo?address={地名}&key={高德密钥}"
        结果 = requests.get(网址, timeout=5).json()
        if 结果['status'] == '1' and 结果['geocodes']:
            数据 = 结果['geocodes'][0]
            经纬 = 数据['location'].split(',')
            return [float(经纬[1]), float(经纬[0]), 数据['adcode']]
    except:
        return None


def 获取实时天气(区域代码):
    try:
        网址 = f"https://restapi.amap.com/v3/weather/weatherInfo?city={区域代码}&key={高德密钥}"
        结果 = requests.get(网址, timeout=5).json()
        实况 = 结果['lives'][0]
        对照表 = {"晴": 0, "多云": 0, "阴": 0, "小雨": 5, "中雨": 15, "大雨": 40, "暴雨": 80, "大暴雨": 150}
        return {"降雨强度": 对照表.get(实况['weather'], 0), "天气状态": 实况['weather'],
                "当前气温": 实况['temperature']}
    except:
        return {"降雨强度": 0, "天气状态": "未知", "当前气温": "25"}


# --- 4. 侧边栏设置 ---
with st.sidebar:
    st.header("⚙️ 监控参数设置")
    显示模式 = st.radio("地图图层", ["卫星实景", "标准街道"])
    st.markdown("---")
    圆圈大小 = st.slider("红色监控区域直径 (米)", 50, 1000, 200)
    地表系数 = st.slider("地表径流系数 (影响积水速度)", 0.5, 1.0, 0.85)
    if st.button("🔄 清空所有推演数据", use_container_width=True):
        st.session_state.历史水位数据 = [0.0]
        st.session_state.监控点坐标 = None
        st.rerun()

# --- 5. 主界面搜索 ---
st.title("🏙️ 城市微尺度内涝实时监控平台")

搜索列, 按钮列 = st.columns([4, 1])
with 搜索列:
    输入框 = st.text_input("搜索地点", placeholder="请输入街道、建筑或城市名称...", label_visibility="collapsed")
with 按钮列:
    if st.button("开始搜索定位", use_container_width=True) and 输入框:
        查找到的坐标 = 搜索地点(输入框)
        if 查找到的坐标:
            st.session_state.地图中心 = [查找到的坐标[0], 查找到的坐标[1]]
            st.session_state.当前区域代码 = 查找到的坐标[2]
            st.session_state.缩放倍率 = 17
            st.rerun()

# --- 6. 地图渲染逻辑 ---
if 显示模式 == "卫星实景":
    底图地址 = 'https://webst01.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}'
else:
    底图地址 = 'https://webrd02.is.autonavi.com/appmaptile?lang=zh_cn&size=1&style=7&x={x}&y={y}&z={z}'

地图对象 = folium.Map(location=st.session_state.地图中心, zoom_start=st.session_state.缩放倍率, tiles=底图地址,
                      attr='高德地图')
folium.TileLayer(tiles='https://wprd02.is.autonavi.com/appmaptile?x={x}&y={y}&z={z}&lang=zh_cn&size=1&style=8',
                 attr='中文标注', overlay=True, control=False).add_to(地图对象)

# 显眼的红色监控圈
if st.session_state.监控点坐标:
    folium.Circle(
        location=st.session_state.监控点坐标,
        radius=圆圈大小 / 2,
        color="red",
        weight=5,
        fill=True,
        fill_color="red",
        fill_opacity=0.3
    ).add_to(地图对象)

# 捕捉用户对地图的操作（拖动、缩放、点击）
地图反馈 = st_folium(地图对象, width="100%", height=500, key="flood_monitor_map")

if 地图反馈:
    # 核心：实时记录地图移动后的中心点，防止回弹
    if 地图反馈.get("center"):
        st.session_state.地图中心 = [地图反馈["center"]["lat"], 地图反馈["center"]["lng"]]
    if 地图反馈.get("zoom"):
        st.session_state.缩放倍率 = 地图反馈["zoom"]
    # 捕捉点击位置，开启监控
    if 地图反馈.get("last_clicked"):
        新点 = [地图反馈["last_clicked"]["lat"], 地图反馈["last_clicked"]["lng"]]
        if 新点 != st.session_state.监控点坐标:
            st.session_state.监控点坐标 = 新点
            st.session_state.历史水位数据 = [0.0]
            st.rerun()

# --- 7. 推演结果展示 (全中文 + 风险说明) ---
if st.session_state.监控点坐标:
    st.markdown("---")
    当前天气 = 获取实时天气(st.session_state.当前区域代码)

    # 模拟水位计算
    上次水位 = st.session_state.历史水位数据[-1]
    入流 = (当前天气['降雨强度'] / 60.0) * 地表系数 * 5.0
    排涝 = 0.35
    当前水位 = max(0.0, 上次水位 + 入流 - 排涝)
    st.session_state.历史水位数据.append(当前水位)

    # 判定预警等级
    if 当前水位 < 10:
        等级, 颜色, 说明 = "✅ 安全", "green", "地面状况良好，无明显积水。"
    elif 当前水位 < 50:
        等级, 颜色, 说明 = "💧 轻度积水", "#3498db", "路面有薄层积水，行车请注意安全。"
    elif 当前水位 < 150:
        等级, 颜色, 说明 = "⚠️ 中度积水", "orange", "积水已没过脚踝，建议非必要不通过低洼地带。"
    else:
        等级, 颜色, 说明 = "🛑 严重内涝", "red", "水位极高！车辆行人严禁通过，请立即避险。"

    st.subheader("📊 实时监控推演面板")
    左栏, 中栏, 右栏 = st.columns([1, 1, 1])
    with 左栏:
        st.metric("实时预估水位", f"{当前水位:.2f} 毫米")
        st.markdown(f"### 当前风险：:{颜色}[{等级}]")
    with 中栏:
        st.metric("气象环境", 当前天气['天气状态'], f"{当前天气['当前气温']} ℃")
        st.write(f"**提示：** {说明}")
    with 右栏:
        对照数据 = {
            "积水高度(mm)": ["低于 10", "10 至 50", "50 至 150", "高于 150"],
            "风险状态": ["安全", "轻度积水", "中度积水", "严重内涝"],
            "通行建议": ["顺畅", "减速", "绕行", "禁止"]
        }
        st.table(pd.DataFrame(对照数据))

    # 绘制中文图表
    图表数据 = pd.DataFrame({"实时积水深度(毫米)": st.session_state.历史水位数据[-60:]})
    st.line_chart(图表数据)

    # 自动刷新推演
    time.sleep(4)
    st.rerun()
else:
    st.info("💡 请在上方搜索框输入地点，然后在地图上【点击具体路段】开始红圈监控推演。")
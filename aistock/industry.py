"""台股 AI 半導體產業鏈分類字典。

每檔個股以 (代號, 名稱, 市場, 供應鏈定位) 表示。
market: "TWSE" = 上市、"TPEx" = 上櫃 —— 決定要打哪個 API、以及 yfinance 的後綴。

註：同一檔個股可能橫跨多個次產業（例如 3037 欣興同時是載板與封裝），
    此處刻意允許重複，讓每個產業籃子都能獨立成立。
"""
from __future__ import annotations

from typing import Dict, List, NamedTuple


class Stock(NamedTuple):
    code: str
    name: str
    market: str   # "TWSE" | "TPEx"
    role: str     # 在供應鏈中的定位


INDUSTRY_MAP: Dict[str, List[Stock]] = {
    "矽光子與 CPO": [
        Stock("3363", "上詮",     "TPEx", "光纖被動元件、CPO 光引擎組裝"),
        Stock("4979", "華星光",   "TPEx", "光收發模組"),
        Stock("3081", "聯亞",     "TPEx", "雷射二極體磊晶與晶片"),
        Stock("6451", "訊芯-KY",  "TWSE", "光通訊模組封裝"),
        Stock("4908", "前鼎",     "TPEx", "光通訊主動元件"),
        Stock("3234", "光環",     "TPEx", "光通訊磊晶與晶片"),
        Stock("4977", "眾達-KY",  "TWSE", "高速光收發模組"),
        Stock("2455", "全新",     "TWSE", "砷化鎵磊晶片"),
        Stock("3163", "波若威",   "TPEx", "光纖被動元件"),
        Stock("6442", "光聖",     "TWSE", "光纖連接與線材"),
    ],
    "高階 PCB / CCL / ABF 載板": [
        Stock("2368", "金像電",   "TWSE", "AI 伺服器高多層板"),
        Stock("2383", "台光電",   "TWSE", "高頻高速銅箔基板"),
        Stock("6213", "聯茂",     "TWSE", "銅箔基板"),
        Stock("6274", "台燿",     "TPEx", "銅箔基板"),
        Stock("3037", "欣興",     "TWSE", "ABF 載板"),
        Stock("8046", "南電",     "TWSE", "ABF 載板"),
        Stock("3189", "景碩",     "TWSE", "IC 載板"),
        Stock("2313", "華通",     "TWSE", "高階印刷電路板"),
        Stock("4958", "臻鼎-KY",  "TWSE", "軟硬板與載板"),
        Stock("6552", "易華電",   "TWSE", "高階軟性載板"),
    ],
    "先進封裝設備與材料 (CoWoS)": [
        Stock("3131", "弘塑",     "TPEx", "濕製程與電鍍設備"),
        Stock("3583", "辛耘",     "TWSE", "先進封裝設備、再生晶圓"),
        Stock("5443", "均豪",     "TPEx", "面板級／晶圓級封裝設備"),
        Stock("6640", "均華",     "TPEx", "IC 封裝與檢測設備"),
        Stock("6187", "萬潤",     "TPEx", "點膠與封裝自動化設備"),
        Stock("3680", "家登",     "TPEx", "EUV 光罩盒、晶圓載具"),
        Stock("3413", "京鼎",     "TWSE", "半導體設備模組代工"),
        Stock("1560", "中砂",     "TWSE", "CMP 鑽石碟、再生晶圓"),
        Stock("6698", "旭暉應材", "TWSE", "石英與半導體應用材料"),
        Stock("6438", "迅得",     "TWSE", "載板與封裝自動化設備"),
    ],
    "IP 與 ASIC 設計服務": [
        Stock("3661", "世芯-KY",  "TWSE", "高階 ASIC 設計服務"),
        Stock("3443", "創意",     "TWSE", "ASIC 設計服務"),
        Stock("6643", "M31",      "TPEx", "矽智財 IP"),
        Stock("6533", "晶心科",   "TWSE", "RISC-V 處理器 IP"),
        Stock("3529", "力旺",     "TPEx", "嵌入式記憶體 IP"),
        Stock("3035", "智原",     "TWSE", "ASIC 設計服務"),
        Stock("8227", "巨有科技", "TPEx", "IC 設計服務與 IP"),
        Stock("4966", "譜瑞-KY",  "TPEx", "高速傳輸介面 IC"),
    ],
    "AI 伺服器散熱": [
        Stock("3017", "奇鋐",     "TWSE", "散熱模組、液冷"),
        Stock("3324", "雙鴻",     "TPEx", "水冷板與散熱模組"),
        Stock("2421", "建準",     "TWSE", "散熱風扇"),
        Stock("3653", "健策",     "TWSE", "均熱片與導熱基板"),
        Stock("6230", "尼得科超眾", "TWSE", "熱管與散熱模組"),
        Stock("3483", "力致",     "TPEx", "散熱模組"),
        Stock("3338", "泰碩",     "TWSE", "熱管、均熱板"),
        Stock("8996", "高力",     "TWSE", "CDU 熱交換器"),
        Stock("4924", "欣厚-KY",  "TPEx", "散熱模組"),
    ],
    "AI 伺服器 ODM 與機構件": [
        Stock("2317", "鴻海",     "TWSE", "AI 伺服器整機與機櫃"),
        Stock("2382", "廣達",     "TWSE", "AI 伺服器 ODM"),
        Stock("2356", "英業達",   "TWSE", "AI 伺服器 ODM"),
        Stock("3231", "緯創",     "TWSE", "AI 伺服器 ODM"),
        Stock("6669", "緯穎",     "TWSE", "雲端資料中心伺服器"),
        Stock("2376", "技嘉",     "TWSE", "GPU 伺服器"),
        Stock("2377", "微星",     "TWSE", "GPU 伺服器與主機板"),
        Stock("8210", "勤誠",     "TWSE", "伺服器機殼"),
        Stock("2059", "川湖",     "TWSE", "伺服器滑軌"),
    ],
    "電源與 BBU": [
        Stock("2308", "台達電",   "TWSE", "電源供應與電力管理"),
        Stock("6412", "群電",     "TWSE", "伺服器電源"),
        Stock("6282", "康舒",     "TWSE", "伺服器電源"),
        Stock("3015", "全漢",     "TWSE", "電源供應器"),
        Stock("2301", "光寶科",   "TWSE", "資料中心電源"),
        Stock("6781", "AES-KY",   "TWSE", "BBU 電池備援模組"),
    ],
    "高速傳輸與網通互連": [
        Stock("3665", "貿聯-KY",  "TWSE", "高速線材與連接器"),
        Stock("3023", "信邦",     "TWSE", "連接器與線束"),
        Stock("2345", "智邦",     "TWSE", "高速交換器"),
        Stock("6285", "啟碁",     "TWSE", "網通設備"),
        Stock("2392", "正崴",     "TWSE", "連接器"),
        Stock("6805", "富世達",   "TWSE", "精密機構與連接"),
        Stock("3689", "湧德",     "TPEx", "網通連接元件"),
    ],
    "上游晶圓、記憶體與封測": [
        Stock("2330", "台積電",   "TWSE", "先進製程晶圓代工"),
        Stock("2454", "聯發科",   "TWSE", "ASIC 與 AI 晶片"),
        Stock("3711", "日月光投控", "TWSE", "封裝測試"),
        Stock("2449", "京元電子", "TWSE", "晶圓測試"),
        Stock("8150", "南茂",     "TWSE", "記憶體封測"),
        Stock("2408", "南亞科",   "TWSE", "DRAM"),
        Stock("2344", "華邦電",   "TWSE", "記憶體"),
        Stock("6488", "環球晶",   "TPEx", "矽晶圓"),
        Stock("3374", "精材",     "TPEx", "晶圓級封裝、TSV"),
    ],
    "測試介面與檢測設備": [
        Stock("6510", "精測",     "TPEx", "探針卡"),
        Stock("2360", "致茂",     "TWSE", "自動測試設備"),
        Stock("6683", "雍智科技", "TPEx", "測試介面板"),
        Stock("6217", "中探針",   "TPEx", "探針與測試治具"),
        Stock("3167", "大量",     "TWSE", "測試治具"),
        Stock("4991", "環宇-KY",  "TPEx", "射頻測試與封裝"),
    ],
    "AI 資料中心供電與重電": [
        Stock("1519", "華城",     "TWSE", "電力變壓器、資料中心供電"),
        Stock("1513", "中興電",   "TWSE", "氣體絕緣開關 GIS、統包工程"),
        Stock("1503", "士電",     "TWSE", "重電設備、配電盤"),
        Stock("1514", "亞力",     "TWSE", "配電盤與電力控制設備"),
        Stock("1504", "東元",     "TWSE", "馬達與機電整合"),
        Stock("1605", "華新",     "TWSE", "電線電纜"),
        Stock("1609", "大亞",     "TWSE", "電線電纜"),
    ],
    "邊緣 AI 與工業電腦": [
        Stock("2395", "研華",     "TWSE", "工業電腦、邊緣 AI 平台"),
        Stock("6414", "樺漢",     "TWSE", "工業電腦與系統整合"),
        Stock("6166", "凌華",     "TWSE", "邊緣運算與嵌入式板卡"),
        Stock("3005", "神基",     "TWSE", "強固型電腦"),
        Stock("6579", "研揚",     "TWSE", "嵌入式主板、邊緣 AI"),
        Stock("3416", "融程電",   "TWSE", "工業級平板與強固電腦"),
    ],
    "AI 記憶體、儲存與控制 IC": [
        Stock("8299", "群聯",     "TPEx", "NAND 控制 IC、AI 儲存方案"),
        Stock("2337", "旺宏",     "TWSE", "NOR / NAND Flash"),
        Stock("5269", "祥碩",     "TWSE", "高速傳輸介面控制 IC"),
        Stock("3260", "威剛",     "TPEx", "記憶體與固態硬碟模組"),
        Stock("5289", "宜鼎",     "TPEx", "工控儲存與嵌入式記憶體"),
        Stock("3006", "晶豪科",   "TWSE", "利基型 DRAM 與 SRAM"),
        Stock("6104", "創惟",     "TPEx", "USB / 儲存介面控制 IC"),
        Stock("4967", "十銓",     "TWSE", "記憶體模組與固態硬碟"),
    ],
}


def all_stocks() -> List[Stock]:
    """回傳去重後的全部成分股（依代號排序）。"""
    seen: Dict[str, Stock] = {}
    for members in INDUSTRY_MAP.values():
        for s in members:
            seen.setdefault(s.code, s)
    return sorted(seen.values(), key=lambda s: s.code)


def industry_names() -> List[str]:
    return list(INDUSTRY_MAP.keys())


def industries_of(code: str) -> List[str]:
    """查某代號隸屬的所有次產業。"""
    return [name for name, members in INDUSTRY_MAP.items()
            if any(s.code == code for s in members)]


def yahoo_symbol(code: str, market: str) -> str:
    """轉成 yfinance 代號：上市 .TW、上櫃 .TWO。"""
    return f"{code}.TW" if market == "TWSE" else f"{code}.TWO"

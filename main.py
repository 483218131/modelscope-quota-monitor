import requests
import os
import concurrent.futures
import unicodedata
from dotenv import load_dotenv

# 尝试从同目录下的 .env 文件加载环境变量 (开源安全最佳实践)
load_dotenv()

# ================= 配置区 =================
# 从环境变量读取 Token，不再硬编码！
API_TOKEN = os.getenv("MODELSCOPE_API_TOKEN")
API_URL = "https://api-inference.modelscope.cn/v1/chat/completions"
ZERO_COST_PROBE = True

# 采用字典结构，真正保留分类信息
MODEL_GROUPS = {
    "🌌 DeepSeek 阵营": [
        "deepseek-ai/DeepSeek-R1",
        "deepseek-ai/DeepSeek-V3.2",
        "deepseek-ai/DeepSeek-V3.2-Exp"
    ],
    "🚀 Qwen (通义千问) 阵营": [
        "Qwen/Qwen3.5-397B-A17B",
        "Qwen/Qwen3.5-122B-A10B",
        "Qwen/Qwen3.5-27B",
        "Qwen/Qwen3-Coder-480B-A35B-Instruct"
    ],
    "🧠 智谱 GLM 阵营": [
        "ZhipuAI/GLM-5",
        "ZhipuAI/GLM-4.6"
    ],
    "✨ Kimi & MiniMax": [
        "moonshotai/Kimi-K2.5",
        "MiniMax/MiniMax-M2.5"
    ],
    "👁️ 多模态 & 视觉理解": [
        "microsoft/Phi-4-reasoning-vision-15B",
        "Qwen/Qwen2.5-VL-72B-Instruct",
        "Qwen/Qwen3-VL-235B-A22B-Instruct"
    ],
    "🎨 AIGC (文生图/视频)": [
        "ai-modelscope/flux.1-dev",
        "FireRedTeam/FireRed-Image-Edit-1.1",
        "Tongyi-MAI/Z-Image-Turbo",
        "Lightricks/LTX-2.3"
    ],
    "📦 其他大厂模型": [
        "meituan-longcat/LongCat-Flash-Lite",
        "XiaomiMiMo/MiMo-V2-Flash"
    ]
}
# ==========================================

def get_display_width(text):
    width = 0
    for char in str(text):
        if unicodedata.east_asian_width(char) in ('W', 'F'):
            width += 2
        else:
            width += 1
    return width

def pad_string(text, target_width):
    text = str(text) if text is not None else "N/A"
    current_width = get_display_width(text)
    padding = max(0, target_width - current_width)
    return text + " " * padding

def safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

def check_single_model(model, headers):
    payload = {
        "model": model,
        "messages": [] if ZERO_COST_PROBE else [{"role": "user", "content": "hi"}],
        "max_tokens": 1
    }
    
    result = {
        "model": model,
        "model_limit": "N/A",
        "model_remain": "N/A",
        "user_limit": "N/A",
        "user_remain": "N/A",
        "status_code": None,
        "remain_int": -1,
        "limit_int": float('inf'),
        "error": None
    }

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=8)
        result["status_code"] = response.status_code
        resp_headers = response.headers

        result["model_limit"] = resp_headers.get("modelscope-ratelimit-model-requests-limit", "N/A")
        result["model_remain"] = resp_headers.get("modelscope-ratelimit-model-requests-remaining", "N/A")
        result["user_limit"] = resp_headers.get("modelscope-ratelimit-requests-limit", "N/A")
        result["user_remain"] = resp_headers.get("modelscope-ratelimit-requests-remaining", "N/A")

        result["remain_int"] = safe_int(result["model_remain"], -1) 
        result["limit_int"] = safe_int(result["model_limit"], float('inf'))

        if response.status_code == 401:
            result["error"] = "Auth Error (Token无效或未实名)"
        elif response.status_code == 429:
            result["error"] = "Rate Limited (被限流)"
        elif result["remain_int"] == -1:
            result["error"] = f"HTTP {response.status_code} (未能获取配额)"

    except requests.exceptions.RequestException:
        result["error"] = "网络/超时异常"
        result["remain_int"] = -2
        
    return result

def fetch_and_sort_limits():
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }

    print("🚀 正在并发查询各模型额度，请稍候...\n")
    
    all_models = [model for group in MODEL_GROUPS.values() for model in group]
    results_map = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_single_model, model, headers): model for model in set(all_models)}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            results_map[res['model']] = res

    if any("Auth Error" in str(r.get("error")) for r in results_map.values()):
        print("🚫 严重错误: Token 无效或未实名，请检查你的 .env 文件配置。")
        return

    user_remain, user_limit = "N/A", "N/A"
    for r in results_map.values():
        if r['user_remain'] != "N/A":
            user_remain = r['user_remain']
            user_limit = r['user_limit']
            break

    print(f"📊 【账号总览】 剩余调用次数: {user_remain} / {user_limit}\n")

    col1, col2, col3 = 42, 12, 12
    divider = "-" * (col1 + col2 + col3 + 10)

    for group_name, models in MODEL_GROUPS.items():
        print(f"\n{group_name}")
        print(divider)
        print(f"| {pad_string('模型名称', col1)} | {pad_string('总限额', col2)} | {pad_string('剩余', col3)} |")
        print(divider)
        
        group_results = [results_map[m] for m in models if m in results_map]
        group_results.sort(key=lambda x: (x['limit_int'], -x['remain_int']))

        for r in group_results:
            if r.get("error") and r['status_code'] != 429:
                err_msg = f"⚠️ {r['error']}"
                print(f"| {pad_string(r['model'], col1)} | {pad_string(err_msg, col2 + col3 + 3)} |")
                continue

            model_name = r['model']
            if r['status_code'] == 429:
                model_name = "🔴 " + model_name 

            print(f"| {pad_string(model_name, col1)} | {pad_string(r['model_limit'], col2)} | {pad_string(r['model_remain'], col3)} |")
        
        print(divider)

if __name__ == "__main__":
    if not API_TOKEN:
        print("❌ 严重错误: 未找到 API Token！")
        print("💡 请确保你已经在代码同级目录下创建了 .env 文件，")
        print("   并填入了 MODELSCOPE_API_TOKEN=你的真实Token")
    else:
        fetch_and_sort_limits()
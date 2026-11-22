"""Narrow local errata; original evidence is never rewritten or approved."""
from __future__ import annotations

import hashlib

ARTICLE_URL = "https://www.codebrick.tech/co-blog/posts/cpu/pipeline-hazard.html"
UNIT_HASHES = {
    "a8df8e0d899f3836": "c126768cecabb6a1ca26187c6649ba89795258ed07fb65a186f635b2aa73f563",
    "3e654e8923329171": "805317ddc3c7d4575783311b9675c8c878ee566d14a075bb0d7ef6dcb3d193f0",
    "1af5ed221a5541b9": "5721c041c67595738f6a9d2af0805494b34c0a384727df04d767fd7211709b99",
    "c960d540f899dc76": "c827aca12e876b750436eb9a9d93da1450aedce6e2a372ee857805b6ee62d1f6",
    "549e507ca8d1fae6": "06d6e48aa368e61eddb95aa3bb432a70216478dcf9aaa170d67f15d9540917ab",
    "c3b124f25a9b0299": "125e845954f68949b887b6e5910944c0608300a1bd1e63f9a320407ca0a90953",
}


def known_conflict(article_url: str, unit: dict) -> bool:
    if article_url.split("#", 1)[0] != ARTICLE_URL:
        return False
    expected = UNIT_HASHES.get(unit.get("id"))
    return bool(expected and hashlib.sha256(unit.get("text", "").encode("utf-8")).hexdigest() == expected)


def repair_summary_text(article_url: str, value: str) -> str:
    if article_url.split("#", 1)[0] != ARTICLE_URL:
        return value
    replacements = [
        ('🔴 判冒险要精确到"哪两条指令的哪两段落在同一个周期"，不能只看寄存器名相同。名字相同但时间上已经错开的，根本不构成冒险',
         '判定 RAW 应确认实际数据依赖，比较新值沿题设可用路径到达输入端的时刻与消费者需要它的时刻；若 T3 读、T5 才写且无旁路或互锁，不同周期仍会读旧值'),
        ('名字相同但时间上已经错开的，根本不构成冒险',
         '名字相同不能单独判断依赖；生产者先写回且数据已可见，或消费者读取的不是该生产者的值时，才可据此排除RAW'),
        ('2 位预测器更准是因为它连错两次才翻转方向。',
         '在线性两位饱和计数器中，00/01预测N、10/11预测T，实际T加1、N减1并在00/11饱和；先预测后更新。强态11遇N先到10，连续第二个N才到01并翻向；弱态10遇一个N就到01并翻向，弱N态01遇T对称。不能推广为任意初态均需两次错误。'),
        ('2 位预测器（饱和计数器）四个状态，需要连续错两次才改变预测方向。',
         '线性两位饱和计数器四态00/01预测N、10/11预测T，先预测后按实际T加1、N减1并饱和；强态需连续两次反向结果才翻向，弱态一次反向结果即可翻向。'),
        ('🔴 2 位预测器更准的全部原因就是"连错两次才翻转方向"，它对偶发的例外有容忍度。',
         '线性两位计数器00/01预测N、10/11预测T；先预测后按T加1、N减1并饱和。强态对一次反向结果有容忍度，而弱态10遇N即到01，弱态01遇T即到10；不能声称任意状态均需连续错两次。'),
        ('相隔 3 条以上的指令通常已经安全。',
         '安全性需按题设流水线长度、停顿、寄存器堆读写相位和实际数据路径复算，不能仅按指令间隔判定。'),
        ('名字相同但时间已错开的不是冒险',
         '同名不能单独确认依赖，不同周期也不能单独排除RAW'),
        ('先标出每条指令的写寄存器（WB 段）与读寄存器（ID 段），再看两条指令的 WB 与 ID 有没有落在同一周期之后。',
         '标出生产者写入新值及消费者实际取值的阶段、周期，核对旁路端点与寄存器堆读写顺序，以新值能否及时到达判断停顿。'),
        ('要精确到哪两段落在同一周期。',
         '应比较具体取值和可见时刻以及题设可用路径，而不把同周期当作必要条件。'),
        ('用哪两段落在同一周期来答',
         '按数据依赖和题设读写时序、可用数据路径逐项判断；不能仅凭两段是否同周期下结论'),
        ('控制冒险代价 [SVG公式/图示：img][公式：=] 判定所在段编号 [SVG公式/图示：img][公式：−1]，',
         '仅当每段1拍、每拍单发射、IF为第1段、分支在第d段末判定且其后年轻指令均需丢弃时，单次预测失败或等待分支的代价为d−1拍；其它取值/预测模型按题设计算，'),
    ]
    for before, after in replacements:
        value = value.replace(before, after)
    return value

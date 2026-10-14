#!/usr/bin/env python3
"""
生成"非中国 IP"清单(CIDR)

= (多个来源的国家段取并集) - 中国 - Cloudflare - 自建服务器 - 私有/保留段

数据源(取并集,单源都有缺口):
  1. metowolf/iplist      RIR 委派数据,粒度细、GitHub Pages CDN,但缺 3.x / 2.16.x 等 AWS 段
  2. Loyalsoldier/geoip   地理库数据,覆盖含 AWS 段,但对小国家/岛屿的判定不同
  Cloudflare              www.cloudflare.com/ips-v4(官方权威列表)

输出: nonchina_ip_list.txt,每行一个 CIDR,已折叠合并
"""
import ipaddress
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

OUT = "nonchina_ip_list.txt"

METOWOLF_INDEX = "https://raw.githubusercontent.com/metowolf/iplist/master/docs/country.md"
METOWOLF_BASE = "https://metowolf.github.io/iplist/data/country/"

GEOIP_CONTENTS = "https://api.github.com/repos/Loyalsoldier/geoip/contents/text?ref=release"
GEOIP_BASE = "https://raw.githubusercontent.com/Loyalsoldier/geoip/release/text/"

CF_V4 = "https://www.cloudflare.com/ips-v4"

# 自建服务器:必须从清单里剔除。
# 否则访问自己的落地/前置节点会被下一跳丢进代理绕一圈,还会抢掉按目的 IP 的分流规则。
SELF_HOSTS = ("141.11.76.7", "185.93.71.211")

# 私有 / 保留段:上游数据若混进这些,内网地址会被判成"国外"
BAD_RANGES = (
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
    "255.255.255.255/32",
)

# 覆盖 IP 数下限(不是条数下限)。
# 折叠程度会随数据源变化,条数不稳定;覆盖量才是真正该守的指标。
# 参考: 全球已分配 IPv4 约 37 亿,正常结果应在 33 亿以上。
MIN_IPS = 3_300_000_000

CIDR_V4 = re.compile(r"^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$")


def fetch(url, timeout=60, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "not-china-ip-list"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # 网络抖动/限流,退避重试
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def get_metowolf_urls():
    """从 country.md 解析出各国清单地址(排除中国)"""
    md = fetch(METOWOLF_INDEX)
    ccs = sorted(set(re.findall(r"data/country/([A-Z]{2})\.txt", md)))
    out = [(cc, METOWOLF_BASE + cc + ".txt") for cc in ccs if cc != "CN"]
    if len(out) < 200:
        print("metowolf 解析出的国家数异常: %d" % len(out), file=sys.stderr)
        sys.exit(1)
    return out


def get_geoip_names():
    """从 GitHub contents API 拿 geoip 的国家文件名(只取两字母国家码)"""
    data = json.loads(fetch(GEOIP_CONTENTS))
    names = [e["name"] for e in data if e.get("name", "").endswith(".txt")]
    if not names:
        print("geoip contents API 未返回 .txt", file=sys.stderr)
        sys.exit(1)
    # text/ 下还有 cloudflare/private/google 等聚合文件,
    # private.txt 含 0.0.0.0/8、10.0.0.0/7 等保留段,必须排除
    out = [n for n in names if re.fullmatch(r"[a-z]{2}\.txt", n) and n != "cn.txt"]
    if len(out) < 200:
        print("geoip 国家数异常: %d" % len(out), file=sys.stderr)
        sys.exit(1)
    return out


def download_all(pairs, label, workers=8):
    """并发下载,任一失败即整体失败(缺源会让清单漏整段)"""
    print("下载 %s (%d 个文件, %d 并发) ..." % (label, len(pairs), workers), flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda kv: (kv[0], fetch(kv[1]), kv[2]), pairs))

    failed = [k for k, t, _ in results if not t.strip()]
    if failed:
        print("%s 下载失败 %d 个: %s" % (label, len(failed), ", ".join(failed)), file=sys.stderr)
        sys.exit(1)

    nets = []
    for _, text, tag in results:
        nets.extend(parse_v4(text))
    print("  %s: %d 条" % (label, len(nets)), flush=True)
    return nets


def main():
    # ---------- 源 1: metowolf ----------
    print("== 源 1: metowolf/iplist ==", flush=True)
    metowolf_pairs = [(cc, url, "metowolf") for cc, url in get_metowolf_urls()]
    mw_nets = download_all(metowolf_pairs, "metowolf", workers=8)
    cn_txt = fetch(METOWOLF_BASE + "CN.txt")

    # ---------- 源 2: Loyalsoldier/geoip ----------
    print("== 源 2: Loyalsoldier/geoip ==", flush=True)
    geoip_pairs = [(n, GEOIP_BASE + n, "geoip") for n in get_geoip_names()]
    geo_nets = download_all(geoip_pairs, "geoip", workers=12)
    geo_cn_txt = fetch(GEOIP_BASE + "cn.txt")

    # ---------- 取并集 ----------
    foreign = mw_nets + geo_nets
    merged_all = list(ipaddress.collapse_addresses(foreign))
    print("两源并集(折叠后): %d 条" % len(merged_all), flush=True)

    # 中国段也取并集(两个源对中国的划分不同,取并集避免漏减)
    cn = list(ipaddress.collapse_addresses(parse_v4(cn_txt) + parse_v4(geo_cn_txt)))
    if not cn:
        print("中国段为空", file=sys.stderr)
        sys.exit(1)
    print("中国段(并集): %d 条" % len(cn), flush=True)

    print("拉取 Cloudflare 官方段 ...", flush=True)
    cf = parse_v4(fetch(CF_V4))
    if not cf:
        print("Cloudflare 段为空", file=sys.stderr)
        sys.exit(1)
    print("Cloudflare: %d 条" % len(cf), flush=True)

    self_nets = [ipaddress.ip_network(x + "/32") for x in SELF_HOSTS]
    bad_nets = [ipaddress.ip_network(c) for c in BAD_RANGES]

    keep = subtract(merged_all, cn)
    print("  减去中国 -> %d 个区间" % len(keep), flush=True)
    keep = subtract(keep, cf)
    print("  减去 Cloudflare -> %d 个区间" % len(keep), flush=True)
    keep = subtract(keep, self_nets)
    print("  减去自建服务器 -> %d 个区间" % len(keep), flush=True)
    keep = subtract(keep, bad_nets)
    print("  减去私有段 -> %d 个区间" % len(keep), flush=True)

    merged = list(ipaddress.collapse_addresses(keep))
    total_ips = sum(n.num_addresses for n in merged)
    print("最终: %d 条, 覆盖 %d 个 IP (%.2f 亿)" % (len(merged), total_ips, total_ips / 1e8), flush=True)

    if total_ips < MIN_IPS:
        print(
            "覆盖量异常偏少 (%d 个 IP < %d),不覆盖输出文件" % (total_ips, MIN_IPS),
            file=sys.stderr,
        )
        sys.exit(1)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(str(n) for n in merged) + "\n")

    print("-> %s (%d 条)" % (OUT, len(merged)))


def parse_v4(text):
    nets = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or not CIDR_V4.match(ln):
            continue
        try:
            nets.append(ipaddress.ip_network(ln, strict=False))
        except ValueError:
            pass
    return nets


def subtract(nets, holes):
    """从 nets 中挖掉 holes(用区间比较,比逐段 subnet_of 快很多)"""
    if not nets or not holes:
        return list(nets)

    def ranges(ns):
        return sorted((int(n.network_address), int(n.broadcast_address)) for n in ns)

    src = ranges(nets)
    hol = ranges(holes)
    out = []
    j, nh = 0, len(hol)
    for a0, a1 in src:
        cur = [(a0, a1)]
        while j < nh and hol[j][1] < a0:
            j += 1
        k = j
        while k < nh and hol[k][0] <= a1:
            h0, h1 = hol[k]
            nxt = []
            for c0, c1 in cur:
                if h1 < c0 or h0 > c1:
                    nxt.append((c0, c1))
                    continue
                if c0 < h0:
                    nxt.append((c0, h0 - 1))
                if c1 > h1:
                    nxt.append((h1 + 1, c1))
            cur = nxt
            if not cur:
                break
            k += 1
        out.extend(cur)

    res = []
    for a, b in out:
        try:
            res.append(ipaddress.ip_network((a, b)))
        except ValueError:
            res.extend(ipaddress.summarize_address_range(ipaddress.ip_address(a), ipaddress.ip_address(b)))
    return res


if __name__ == "__main__":
    main()

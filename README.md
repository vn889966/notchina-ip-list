# notchina-ip-list

非中国 IPv4 CIDR 清单，每天 07:00（北京时间）由 GitHub Actions 自动更新。

## 算法

```
(metowolf/iplist ∪ Loyalsoldier/geoip) - CN - Cloudflare - 自建服务器 - 私有/保留段
```

多源取并集，因为单源都有缺口：

| 数据源 | 优点 | 缺点 |
|---|---|---|
| [metowolf/iplist](https://github.com/metowolf/iplist) | RIR 委派数据，粒度细，走 GitHub Pages CDN | 缺 3.x / 2.16.x 等 AWS 段 |
| [Loyalsoldier/geoip](https://github.com/Loyalsoldier/geoip) | 地理库数据，覆盖 AWS 段 | 对小国家/岛屿的判定与 RIR 不同 |
| [Cloudflare ips-v4](https://www.cloudflare.com/ips-v4) | 官方权威列表 | — |

## 用法

直接拉列表：

```bash
curl -sLO https://raw.githubusercontent.com/vn889966/notchina-ip-list/main/nonchina_ip_list.txt
```

## 文件

| 文件 | 说明 |
|---|---|
| `nonchina_ip_list.txt` | 产物，每行一个 CIDR，已折叠合并 |
| `generate.py` | 生成脚本，只依赖 Python 标准库 |
| `.github/workflows/update-list.yml` | 定时任务，每天 07:00 北京时间 |

## 本地跑

```bash
python3 generate.py
```

依赖 Python 3.8+，无需 `pip install`。

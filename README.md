# SyncNext Personal Feed

这个目录会生成你自己的 SyncNext 订阅频道列表。

## 输出文件

- `public/sourcesv3.json`: 给 SyncNext 使用的订阅源 JSON。
- `public/update-report.json`: 最近一次更新报告。
- `data/seed_sources.json`: 本地保底源。网络失败时仍然可以生成订阅。
- `data/source_feeds.json`: 可继续添加公开的 SyncNext JSON 源地址，用于自动合并。
- `data/tvbox_feeds.json`: 可添加 TVBox 配置 URL，脚本会导入可直连的 CMS/VOD 源。

## 更新

```bash
python3 scripts/update_syncnext.py
```

如果当前网络不能访问外部地址，可以先用离线种子生成：

```bash
python3 scripts/update_syncnext.py --offline
```

## 一次性短链接设置

SyncNext 需要一个公网可访问的 JSON 地址。当前已经发布到 GitHub：

- 仓库：`https://github.com/likilu2002/syncnext-feed`
- 推荐订阅地址：`https://raw.githubusercontent.com/likilu2002/syncnext-feed/main/public/sourcesv3.json`
- 短链接：`https://tinyurl.com/28kdwnxj`

短链接也会写入 `public/shortlink.txt`。

设置路径按官方说明是：SyncNext 菜单 -> 订阅频道列表，填入这个短链接即可。之后只要同一个公网 URL 的内容持续更新，SyncNext 里不需要反复换地址。

## 继续扩展

把新的公开订阅 JSON 加到 `data/source_feeds.json`，脚本会自动拉取、合并、按 `Top/Priority/name` 排序，并用 `api` 去重。

如果你有 TVBox 接口，把它加到 `data/tvbox_feeds.json`：

```json
[
  {
    "name": "my-tvbox",
    "url": "https://example.com/tvbox.json"
  }
]
```

脚本会读取 `sites` 并导入可直连的 CMS/VOD API。需要 jar、JS、drpy 或专用爬虫的 TVBox 站点会记录到 `public/update-report.json` 的 `tvbox_skipped` 里。

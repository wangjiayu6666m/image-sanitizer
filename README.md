# SANITIZE // 图像脱敏系统

去除 EXIF 元数据 + 对抗隐写水印的 Docker 网页服务。

## 快速启动

```bash
docker compose up -d --build
```

浏览器打开 http://localhost:8080

## 功能

| 操作 | 原理 | 对抗目标 |
|------|------|---------|
| EXIF 清除 | 重建像素数据，不携带元数据 | GPS、设备序列号、时间戳 |
| PNG chunk 清除 | 过滤非必要 PNG 块 | tEXt、iTXt、eXIf chunk |
| 高斯噪声注入 | 向像素值加随机噪声 | LSB 隐写水印 |
| 重采样攻击 | 缩小再放大 | 像素级位置水印 |
| JPEG 重压缩 | 重新 JPEG 编码 | DCT 域隐写水印 |

## 架构

```
browser → caddy(:8080) → /api/* → Flask(:5000)
                       ↓
                  index.html
```

## 停止

```bash
docker compose down
```

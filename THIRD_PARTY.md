# 第三方组件与致谢

- 模拟器按 GPL-3.0 发布，见 [COPYING](COPYING)。`vendor/s6502.c` 基于 HelloClyde 的 [BBK9288-gam4980](https://github.com/HelloClyde/BBK9288-gam4980) 中的 GPL-3.0 CPU 实现，增加了中断返回及等待、停止指令的主机钩子。
- 硬件研究参考了无云的 [BBK-simulator](https://gitee.com/BA4988/BBK-simulator/tree/BA4988/BA4988)、宋文武的 [gam4980](https://codeberg.org/iyzsong/gam4980) 和 [MAME 的 ST2xxx 实现](https://github.com/mamedev/mame/tree/master/src/devices/cpu/m6502)。
- GNU Unifont 18.0.01 版权及许可见 [字体说明](vendor/fonts/README.md)。原始字形文件与 SIL OFL 1.1、GPLv2+ 加字体嵌入例外的条款位于同一目录。
- 扫雷和与之链接的运行库来自 [BBK7980 SDK v1.1.1](https://github.com/HelloClyde/BBK7980-sdk/releases/tag/v1.1.1)。发行包 `demo-source/` 附带对应源码、图标、许可证和构建信息，其中扫雷方向键已按 7980 真机布局修正。cc65 工具链用于构建，便携包附其许可文本。
- 便携包使用 Python、Tcl/Tk、Pillow、pefile 和 PyInstaller，第三方许可随包附上。
- GitHub Release 单独提供的系统镜像包含经授权分发的步步高 V1.10 固件和原厂应用，相关权利归各权利人。GNU GPLv3 适用于模拟器源码。模拟器也支持从官网升级包生成系统镜像。

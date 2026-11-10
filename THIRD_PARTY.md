# 数据、字体与参考资料

## MaleCNS v1.0

数据来自 FlyEM（HHMI Janelia）、University of Cambridge、MRC Laboratory of Molecular Biology 和 Google Research 的 MaleCNS 项目。

- Berg et al., *Sexual dimorphism in the complete connectome of the Drosophila male central nervous system*.
- 官方项目：[https://male-cns.janelia.org/](https://male-cns.janelia.org/)
- 数据与许可：[下载页](https://male-cns.janelia.org/download/)，**CC BY 4.0**。
- 本项目进行细胞筛选、连接聚合、符号假设、归一化和视觉/动作映射。这些修改和动力学不由数据作者背书。
- 大型原始表和预处理权重均在项目根目录的 `brain_data/` 中，不随源代码打包。

## Noto Sans CJK SC

随包字体 `flybrain/assets/fonts/NotoSansCJKsc-Regular.otf` 来自 [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk)。采用 SIL Open Font License 1.1，完整许可随附在 `flybrain/assets/fonts/LICENSE`。

## 软件依赖

Pygame Community Edition、NumPy、SciPy、Apache Arrow / PyArrow 的许可由各自发行包提供。项目使用公开 API，未修改这些库。

## 技术参考

- [fly-endfield](https://github.com/xiaotaoQWQ/fly-endfield)：游戏/感官/神经输出的接口与状态面板思路。
- [Fly64](https://github.com/ornata/fly)：全连接组到游戏的闭环、下行神经元群解码和可重复验证思路。
- [BetterGI](https://github.com/babalae/better-genshin-impact)：屏幕与模拟输入的游戏自动化架构参考。

本项目独立实现游戏、数据处理和神经仿真，不包含上述三个仓库的源代码或游戏素材。

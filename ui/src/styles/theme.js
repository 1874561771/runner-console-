/* Naive UI 主题对齐旧版设计令牌（design-tokens.css）
   --bg #F4F4EF / --ink #1A1D20 / --accent #D9480F / --line #E3E4DC */
export const themeOverrides = {
  common: {
    primaryColor: "#D9480F",
    primaryColorHover: "#B23A0B",
    primaryColorPressed: "#B23A0B",
    primaryColorSuppl: "#B23A0B",
    bodyColor: "#F4F4EF",
    cardColor: "#FFFFFF",
    modalColor: "#FFFFFF",
    popoverColor: "#FFFFFF",
    borderColor: "#E3E4DC",
    dividerColor: "#EDEEE6",
    textColorBase: "#1A1D20",
    textColor1: "#1A1D20",
    textColor2: "#5F646B",
    textColor3: "#8A8F96",
    borderRadius: "6px",
    borderRadiusSmall: "4px",
    fontSize: "13.5px",
    fontFamily:
      '"Segoe UI", "PingFang SC", "Microsoft YaHei", "JetBrains Mono", Consolas, monospace',
    fontFamilyMono: '"JetBrains Mono", "Sarasa Gothic SC", Consolas, monospace',
  },
  Card: { borderRadius: "8px" },
  DataTable: { thColor: "#FAFAF8", tdColor: "#FFFFFF" },
  Menu: { itemColorActive: "#FDEEE6", itemTextColorActive: "#B23A0B" },
};

<script setup>
import { NCard, NButton, useMessage } from "naive-ui";

defineProps({
  /* 占位页：显示本页迁移计划与旧版跳转 */
  note: { type: String, default: "" },
});
const msg = useMessage();
function gotoLegacy() {
  msg.info("在浏览器地址栏把 /v2/ 改成 / 即可回到旧版页面");
}
</script>

<template>
  <n-card :title="$route.meta.title + ' · 新版建设中'">
    <p style="margin-top:0">
      {{ note || "本页将在后续阶段迁移为 Vue 3 + Naive UI 实现；当前可继续使用旧版页面。" }}
    </p>
    <n-button size="small" @click="gotoLegacy">如何回到旧版</n-button>
  </n-card>
</template>

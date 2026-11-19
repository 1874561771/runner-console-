<script setup>
import { computed } from "vue";
import { NTag } from "naive-ui";

const props = defineProps({
  status: { type: String, default: "" },
  size: { type: String, default: "small" },
});

const STATUS = {
  running: { type: "info", text: "运行中" },
  done: { type: "success", text: "已完成" },
  stopped: { type: "warning", text: "已停止" },
  failed: { type: "error", text: "失败" },
  pass: { type: "success", text: "通过" },
  fail: { type: "error", text: "失败" },
  setup_fail: { type: "error", text: "Setup 失败" },
  broken: { type: "warning", text: "异常" },
  started: { type: "info", text: "已发起" },
  start_error: { type: "error", text: "发起失败" },
  missed: { type: "warning", text: "已错过" },
  ok: { type: "success", text: "完成" },
};

const view = computed(() => STATUS[props.status] || {
  type: "default",
  text: props.status || "未知",
});
</script>

<template>
  <n-tag :type="view.type" :size="size" :bordered="false">{{ view.text }}</n-tag>
</template>

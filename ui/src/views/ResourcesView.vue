<script setup>
/* 资源页：环境 / 我的上传 / 我的套件（P3） */
import { NTabs, NTabPane } from "naive-ui";
import EnvsPane from "../components/resources/EnvsPane.vue";
import UploadsPane from "../components/resources/UploadsPane.vue";
import SuitesPane from "../components/resources/SuitesPane.vue";
</script>

<template>
  <div class="view-head">
    <h1 class="view-title">资源</h1>
    <span class="faint" style="font-size: 12.5px">环境、上传的 suite / 脚本、保存的套件</span>
  </div>
  <n-card size="small" :content-style="{ padding: '6px 14px 14px' }">
    <n-tabs type="line" size="small" animated default-value="envs">
      <n-tab-pane name="envs" tab="环境" display-directive="show:lazy"><EnvsPane /></n-tab-pane>
      <n-tab-pane name="uploads" tab="我的上传" display-directive="show:lazy"><UploadsPane /></n-tab-pane>
      <n-tab-pane name="suites" tab="我的套件" display-directive="show:lazy"><SuitesPane /></n-tab-pane>
    </n-tabs>
  </n-card>
</template>

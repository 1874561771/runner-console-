<script setup>
import { NConfigProvider, NMessageProvider, NDialogProvider } from "naive-ui";
import { themeOverrides } from "./styles/theme.js";
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-message-provider placement="top" :duration="2600">
      <n-dialog-provider>
        <router-view />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

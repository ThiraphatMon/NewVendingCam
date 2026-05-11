<script setup>
import { useRoute, useRouter } from 'vue-router'

import Sidebar from "@/views/sidebar/SidebarView.vue";
import { Modal } from 'flowbite'

const router = useRouter()
const route = useRoute()

</script>

<template>
  <div style="display: flex; min-height: 100vh;"> 
<!-- sidebar -->
    <Sidebar />

<!-- body -->
    <div style="flex: 1; padding: 20px; padding-left: calc((var(--spacing) * 64) + 20px);">
      <router-view />
    </div>
  </div>
</template>

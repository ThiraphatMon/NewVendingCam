<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import ConfigureService from '@/services/ConfigureService.js'

const route = useRoute()
const machineId = route.params.machine_id

const imageUrl = ref('')

const frameW = 640
const frameH = 480

const points = ref([
  { x: 120, y: 120 },
  { x: 520, y: 120 },
  { x: 520, y: 360 },
  { x: 120, y: 360 }
])

const draggingIndex = ref(null)

function getPoint(event) {
  const rect = event.currentTarget.getBoundingClientRect()

  const scaleX = frameW / rect.width
  const scaleY = frameH / rect.height

  const x = Math.round((event.clientX - rect.left) * scaleX)
  const y = Math.round((event.clientY - rect.top) * scaleY)

  return {
    x: Math.max(0, Math.min(frameW, x)),
    y: Math.max(0, Math.min(frameH, y))
  }
}

function pointsToString(pts) {
  return pts.map(point => `${point.x},${point.y}`).join(' ')
}

function startDrag(index, event) {
  draggingIndex.value = index
  event.currentTarget.setPointerCapture?.(event.pointerId)
}

function dragMove(event) {
  if (draggingIndex.value === null) return

  const point = getPoint(event)

  points.value[draggingIndex.value] = point
}

function stopDrag() {
  draggingIndex.value = null
}

const payload = computed(() => ({
  frame: {
    width: frameW,
    height: frameH
  },
  roi_type: 'quad',
  points: points.value
}))

async function loadROI() {
  try {
    const res = await ConfigureService.get_one(machineId)

    console.log('ROI from server:', res.data)

    if (res.data?.points?.length === 4) {
      points.value = res.data.points
    }

  } catch (error) {
    console.error('Load ROI error:', error)
  }
}

async function loadLatestImage() {
  try {
    const res = await ConfigureService.get_latest_image(machineId)

    console.log('Latest image from server:', res.data)

    // สมมติ backend ส่งกลับมาแบบนี้:
    // { image_url: "/images/TXN-20260507-141234_landed.jpg" }

    if (res.data?.image_url) {
      imageUrl.value = `${import.meta.env.VITE_API_URL}${res.data.image_url}?t=${Date.now()}`
    }

  } catch (error) {
    console.error('Load latest image error:', error)
  }
}

async function saveROI() {
  try {
    console.log('Save ROI:', payload.value)

    await ConfigureService.update(machineId, payload.value)
  } catch (error) {
    console.error('Save ROI error:', error)
  }
}

async function resetROI() {
  try {
    points.value = [
      { x: 120, y: 120 },
      { x: 520, y: 120 },
      { x: 520, y: 360 },
      { x: 120, y: 360 }
    ]

    console.log('Reset ROI:', payload.value)

    await ConfigureService.update(machineId, payload.value)

  } catch (error) {
    console.error('Reset ROI error:', error)
  }
}

// add reset func

onMounted(async () => {
  await loadROI()
  await loadLatestImage()
})
</script>

<template>
  <div class="p-6">
    <h1 class="text-xl font-bold mb-2">
      Configure ROI
    </h1>

    <p class="text-sm text-gray-600 mb-4">
      Drag 4 corner points to configure ROI
    </p>

    <div
      class="relative w-[640px] h-[480px] select-none rounded-lg overflow-hidden border border-blue-700"
      @pointermove.prevent="dragMove"
      @pointerup.prevent="stopDrag"
      @pointerleave.prevent="stopDrag"
    >
      <img
        v-if="imageUrl"
        :src="imageUrl"
        class="w-full h-full object-cover"
        draggable="false"
      />

      <div
        v-else
        class="w-full h-full flex items-center justify-center bg-gray-200 text-gray-600"
      >
        Loading image...
      </div>

      <svg
        class="absolute inset-0 w-full h-full"
        :viewBox="`0 0 ${frameW} ${frameH}`"
      >
        <polygon
          :points="pointsToString(points)"
          fill="rgba(37, 99, 235, 0.25)"
          stroke="rgb(37, 99, 235)"
          stroke-width="3"
        />

        <circle
          v-for="(point, index) in points"
          :key="index"
          :cx="point.x"
          :cy="point.y"
          r="10"
          fill="rgb(220, 38, 38)"
          stroke="white"
          stroke-width="3"
          class="cursor-move"
          @pointerdown.prevent.stop="startDrag(index, $event)"
        />

        <text
          v-for="(point, index) in points"
          :key="`label-${index}`"
          :x="point.x + 12"
          :y="point.y - 12"
          fill="#111827"
          stroke="white"
          stroke-width="3"
          paint-order="stroke"
          font-size="16"
          font-weight="700"
        >
          P{{ index + 1 }}
        </text>
      </svg>
    </div>

    <div class="flex gap-3 mt-4">
      <div
        @click="saveROI"
        class="text-white bg-gradient-to-r from-cyan-500 to-blue-500 hover:bg-gradient-to-bl focus:ring-4 focus:outline-none focus:ring-cyan-300 dark:focus:ring-cyan-800 font-medium rounded-base text-sm px-4 py-2.5 text-center leading-5 cursor-pointer"
      >
        Save ROI
      </div>
      <div
        @click="resetROI"
        class="text-white bg-gradient-to-r from-red-400 via-red-500 to-red-600 hover:bg-gradient-to-br focus:ring-4 focus:outline-none focus:ring-red-300 dark:focus:ring-red-800 font-medium rounded-base text-sm px-4 py-2.5 text-center leading-5 cursor-pointer"
      >
        Reset ROI
      </div>
    </div>

<!-- ตัวอย่างข้อมูลที่ส่งออก -->
    <!-- <pre class="mt-4 w-[640px] bg-gray-100 p-3 rounded text-sm overflow-auto">{{ payload }}</pre> -->
    </div>
</template>
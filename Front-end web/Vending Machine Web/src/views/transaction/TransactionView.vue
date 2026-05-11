<script setup>
import { useRoute, useRouter } from 'vue-router'
import { reactive, inject, onBeforeMount, onMounted, onBeforeUnmount, onUnmounted, watch, nextTick, ref,computed } from "vue";

import TransactionService from '@/services/TransactionService.js'
import { Modal } from 'flowbite'

const modal_element = ref(null)
let modal = null

const selectedItem = ref(null)

const openImageModal = (item) => {
  selectedItem.value = item
  if (modal) modal.show()
}
const closeImageModal = () => modal.hide()

const router = useRouter()
const route = useRoute()

const machine_id = route.params.machine_id

var transaction_data = reactive({
  filter: {
    keyword: "",
  },
  transactions: [],
});

const changePage = (page_router_name) => {
  router.push(page_router_name)
}

const getTransactions = () => {
    TransactionService.get_list(machine_id, transaction_data.filter)
    .then((response) => {
        console.log(response.data);

        transaction_data.transactions = response.data.transactions;
    })
    .catch((error) => {
        console.error('Error fetching data:', error);
    })
}

function formatTransactionTime(transaction_id) {
  // TXN-20260506-140121
  const parts = transaction_id.split("-")

  const datePart = parts[1] // 20260506
  const timePart = parts[2] // 140121

  const year = datePart.slice(0, 4)
  const month = datePart.slice(4, 6)
  const day = datePart.slice(6, 8)

  const hour = timePart.slice(0, 2)
  const minute = timePart.slice(2, 4)
  const second = timePart.slice(4, 6)

  return `${day}/${month}/${year} ${hour}:${minute}:${second}`
}

function formatTransactionTimeForModal(transaction_id) {
  if (!transaction_id) return ""

  const parts = transaction_id.split("-")

  if (parts.length < 3) return transaction_id

  const datePart = parts[1]
  const timePart = parts[2]

  if (!datePart || !timePart) return transaction_id

  const year = datePart.slice(0, 4)
  const month = datePart.slice(4, 6)
  const day = datePart.slice(6, 8)

  const hour = timePart.slice(0, 2)
  const minute = timePart.slice(2, 4)
  const second = timePart.slice(4, 6)

  return `${day}/${month}/${year} ${hour}:${minute}:${second}`
}

function getImageUrl(path) {
  if (!path) return ""

  const fileName = path.replaceAll("\\", "/").split("/").pop()

  return `${import.meta.env.VITE_API_URL}/images/${fileName}`
}

onMounted(() => {
  getTransactions();
  modal = new Modal(modal_element.value, {
    placement: 'center',
    backdrop: 'dynamic',
  })
});

watch(
  () => transaction_data.filter.keyword,
  () => {
    getTransactions()
  }
)

</script>

<template>
  <div class = "text-4xl font-bold mb-8">
    TRANSACTION PAGE
  </div>
  <div>
      <input v-model="transaction_data.filter.keyword" type="text" id="visitors" class="bg-neutral-secondary-medium border border-default-medium text-heading text-sm rounded-base focus:ring-brand focus:border-brand block w-full px-2.5 py-2 shadow-xs placeholder:" placeholder="Log search" required />
    </div>
    <div class="grid grid-cols-2 gap-6" style="padding-top: 20px">
      <div
        v-for="item in transaction_data.transactions"
        :key="item.id"
        style="cursor: pointer; pointer ;"
        class="bg-gray-100 rounded-xl shadow p-4 hover:shadow-lg transition cursor-pointer block flex gap-6"
      >
        <div class="grid grid-cols-[220px_1fr] gap-y-8 gap-x-6 w-full">
            <p>{{ formatTransactionTime(item.transaction_id) }}</p>
            <p></p>
            <p>{{ item.land_time }}</p>
            <div class="flex items-center gap-2 justify-self-start whitespace-nowrap">
                <p>Status: </p>
                <p>{{item.event_status}}</p>
            </div>
        </div>
        <div class="ml-auto">
            <img
              :src="getImageUrl(item.landed_image_path)"
              class="w-32 h-24 object-cover rounded-lg"
              @click="openImageModal(item)"
            />
        </div>
        
      </div>
    </div>

    <!-- config btn -->
    <RouterLink :to="`/api/machines/${machine_id}/roi`" type="button" class="flex text-white bg-gradient-to-br from-purple-600 to-blue-500 hover:bg-gradient-to-bl focus:ring-4 focus:outline-none focus:ring-blue-300 dark:focus:ring-blue-800 font-medium rounded-base text-sm px-4 py-2.5 text-center leading-5" style="position: fixed; right: 30px; bottom: 30px; padding: 20px;">
    <svg class="w-5 h-5 me-1.5 -ms-0.5" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24">
      <path stroke="currentColor" stroke-linecap="round" stroke-width="2" d="M20 6H10m0 0a2 2 0 1 0-4 0m4 0a2 2 0 1 1-4 0m0 0H4m16 6h-2m0 0a2 2 0 1 0-4 0m4 0a2 2 0 1 1-4 0m0 0H4m16 6H10m0 0a2 2 0 1 0-4 0m4 0a2 2 0 1 1-4 0m0 0H4"/>
    </svg>
    Configure ROI
    </RouterLink>

    <!-- modal -->

        <!-- Main modal -->
    <div ref="modal_element" tabindex="-1" aria-hidden="true" class="hidden overflow-y-auto overflow-x-hidden fixed top-0 right-0 left-0 z-50 justify-center items-center w-full md:inset-0 h-[calc(100%-1rem)] max-h-full">
        <div class="relative p-4 w-full max-w-2xl max-h-full">
            <!-- Modal content -->
            <div class="relative bg-neutral-primary-soft border border-default rounded-base shadow-sm p-4 md:p-6">
                <!-- Modal header -->
                <div class="flex items-center justify-between border-b border-default pb-4 md:pb-5">
                    <h3 class="text-lg font-medium text-heading">
                        {{ selectedItem?.land_time || formatTransactionTimeForModal(selectedItem?.transaction_id) }}
                    </h3>
                    <button @click="closeImageModal()" type="button" class="text-body bg-transparent hover:bg-neutral-tertiary hover:text-heading rounded-base text-sm w-9 h-9 ms-auto inline-flex justify-center items-center">
                        <svg class="w-5 h-5" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18 17.94 6M18 18 6.06 6"/></svg>
                        <span class="sr-only">Close modal</span>
                    </button>
                </div>
                <!-- Modal body -->
                <div class="space-y-4 md:space-y-6 py-4 md:py-6">
                    <p class="leading-relaxed text-body">
                      <img
                        :src="getImageUrl(selectedItem?.landed_image_path)"
                      />
                    </p>
                </div>
            </div>
        </div>
    </div>

</template>
<script setup>
import { useRoute, useRouter } from 'vue-router'
import { reactive, inject, onBeforeMount, onMounted, onBeforeUnmount, onUnmounted, watch, nextTick, ref,computed } from "vue";

import MachineService from '@/services/MachineService.js'

const router = useRouter()
const route = useRoute()

const changePage = (page_router_name) => {
  router.push(page_router_name)
}

var machine_data = reactive({
  filter: {
    keyword: "",
  },
  machines: [],
});

const getMachines = () => {
    MachineService.get_list(machine_data.filter)
    .then((response) => {
        console.log(response.data);

        machine_data.machines = response.data.machines;
    })
    .catch((error) => {
        console.error('Error fetching data:', error);
    })
}

// modal

import { Modal } from 'flowbite'

const update_modal_element = ref(null)

let updateModal = null

const updateForm = reactive({
  machine_id: '',
  name: '',
  location: '',
  note: '',
  image_path: '',
})

const selectedMachineId = ref(null)

const openUpdateMachine = (item) => {
  selectedMachineId.value = item.machine_id

  updateForm.machine_id = item.machine_id || ''
  updateForm.name = item.name || ''
  updateForm.location = item.location || ''
  updateForm.note = item.note || ''
  updateForm.image_path = item.image_path || ''

  updateModal.show()
}

const closeUpdateMachine = () => {
  updateModal.hide()
}

const submitUpdateMachine = async () => {
  try {
    await MachineService.update(selectedMachineId.value, {
      machine_id: updateForm.machine_id,
      name: updateForm.name,
      location: updateForm.location,
      note: updateForm.note,
      image_path: updateForm.image_path,
    })

    closeUpdateMachine()
    getMachines()
  } catch (error) {
    console.error('Update machine error:', error)
  }
}

onMounted(() => {
  getMachines()
  updateModal = new Modal(update_modal_element.value, {
    placement: 'center',
    backdrop: 'dynamic',
  })
})

watch(
  () => machine_data.filter.keyword,
  () => {
    getMachines()
  }
)
</script>

<template>
  <div class = "text-4xl font-bold mb-8">
    MACHINES PAGE
  </div>
  <div>
      <input v-model="machine_data.filter.keyword" type="text" id="visitors" class="bg-neutral-secondary-medium border border-default-medium text-heading text-sm rounded-base focus:ring-brand focus:border-brand block w-full px-2.5 py-2 shadow-xs placeholder:" placeholder="Log search" required />
    </div>
    <div class="grid grid-cols-4 gap-6" style="padding-top: 20px">
      <RouterLink
        v-for="item in machine_data.machines"
        :key="item.id"
        :to="`/api/machines/${item.machine_id}`"
        class="relative bg-gray-100 rounded-xl shadow p-4 hover:shadow-lg transition cursor-pointer block"
      >
        <img :src="item.image_path" class="w-full h-50 object-cover rounded-lg"/>
        <h3 class="text-xl font-semibold mt-4">{{ item.machine_id }}</h3>
        <p class="text-gray-600 mt-1">location: {{ item.location }}</p>

        <div @click.prevent.stop="openUpdateMachine(item)" type="button" class="absolute bottom-4 right-4 text-body bg-neutral-primary border border-default hover:bg-neutral-secondary-soft hover:text-heading focus:ring-4 focus:ring-neutral-tertiary font-medium leading-5 rounded-base text-sm p-2.5 focus:outline-none">
          <svg class="w-5 h-5" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24">
            <path stroke="currentColor" stroke-linecap="round" stroke-width="2" d="M20 6H10m0 0a2 2 0 1 0-4 0m4 0a2 2 0 1 1-4 0m0 0H4m16 6h-2m0 0a2 2 0 1 0-4 0m4 0a2 2 0 1 1-4 0m0 0H4m16 6H10m0 0a2 2 0 1 0-4 0m4 0a2 2 0 1 1-4 0m0 0H4"/>
          </svg>
        </div>
      </RouterLink>
    </div>


    <!-- modal สำหรับ update machine -->
    <div
      id="update_modal_element"
      ref="update_modal_element"
      tabindex="-1"
      aria-hidden="true"
      class="hidden overflow-y-auto overflow-x-hidden fixed top-0 right-0 left-0 z-50 justify-center items-center w-full md:inset-0 h-[calc(100%-1rem)] max-h-full"
    >
      <div class="relative p-4 w-full max-w-md max-h-full">
        <div class="relative bg-neutral-primary-soft border border-default rounded-base shadow-sm p-4 md:p-6">
        
          <div class="flex items-center justify-between border-b border-default pb-4 md:pb-5">
            <h3 class="text-lg font-medium text-heading">
              Update Machine {{selectedMachineId}}
            </h3>
    
            <button
              @click="closeUpdateMachine()"
              type="button"
              class="text-body bg-transparent hover:bg-neutral-tertiary hover:text-heading rounded-base text-sm w-9 h-9 ms-auto inline-flex justify-center items-center"
            >
              <svg class="w-5 h-5" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="none" viewBox="0 0 24 24">
                <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18 17.94 6M18 18 6.06 6"/>
              </svg>
            </button>
          </div>
    
          <form @submit.prevent="submitUpdateMachine">
            <div class="grid gap-4 grid-cols-2 py-4 md:py-6">
    
              <div class="col-span-2">
                <label class="block mb-2.5 text-sm font-medium text-heading">
                  Name
                </label>
                <input
                  v-model="updateForm.name"
                  type="text"
                  class="bg-neutral-secondary-medium border border-default-medium text-heading text-sm rounded-base focus:ring-brand focus:border-brand block w-full px-3 py-2.5 shadow-xs placeholder:text-body"
                  placeholder="Machine name"
                />
              </div>
    
              <div class="col-span-2">
                <label class="block mb-2.5 text-sm font-medium text-heading">
                  Location
                </label>
                <input
                  v-model="updateForm.location"
                  type="text"
                  class="bg-neutral-secondary-medium border border-default-medium text-heading text-sm rounded-base focus:ring-brand focus:border-brand block w-full px-3 py-2.5 shadow-xs placeholder:text-body"
                  placeholder="Location"
                />
              </div>
    
              <div class="col-span-2">
                <label class="block mb-2.5 text-sm font-medium text-heading">
                  Image Path
                </label>
                <input
                  v-model="updateForm.image_path"
                  type="text"
                  class="bg-neutral-secondary-medium border border-default-medium text-heading text-sm rounded-base focus:ring-brand focus:border-brand block w-full px-3 py-2.5 shadow-xs placeholder:text-body"
                  placeholder="/images/machine.jpg"
                />
              </div>
    
              <div class="col-span-2">
                <label class="block mb-2.5 text-sm font-medium text-heading">
                  Note
                </label>
                <textarea
                  v-model="updateForm.note"
                  rows="4"
                  class="block bg-neutral-secondary-medium border border-default-medium text-heading text-sm rounded-base focus:ring-brand focus:border-brand w-full p-3.5 shadow-xs placeholder:text-body"
                  placeholder="Write note here"
                ></textarea>
              </div>
    
            </div>
    
            <div class="flex items-center space-x-4 border-t border-default pt-4 md:pt-6">
              <button
                type="submit"
                class="inline-flex items-center text-white bg-brand hover:bg-brand-strong box-border border border-transparent focus:ring-4 focus:ring-brand-medium shadow-xs font-medium leading-5 rounded-base text-sm px-4 py-2.5 focus:outline-none"
              >
                Save
              </button>
    
              <button
                type="button"
                class="text-body bg-neutral-secondary-medium box-border border border-default-medium hover:bg-neutral-tertiary-medium hover:text-heading focus:ring-4 focus:ring-neutral-tertiary shadow-xs font-medium leading-5 rounded-base text-sm px-4 py-2.5 focus:outline-none"
                @click="closeUpdateMachine()"
              >
                Cancel
              </button>
            </div>
          </form>
    
        </div>
      </div>
    </div>
</template>
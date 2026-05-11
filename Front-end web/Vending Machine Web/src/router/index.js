import { createRouter, createWebHistory } from "vue-router"

const routes = [
  {
    path: "/",
    component: () => import("../views/MainView.vue"),
    children: [
      {
        path: "api/machines/:machine_id/",
        component: () => import("../views/transaction/TransactionView.vue"),
      },
      {
        path: "api/machines",
        component: () => import("../views/machine/MachineView.vue"),
      },
      {
        path: "api/machines/:machine_id/roi",
        component: () => import("../views/configure/ConfigureView.vue"),
      },
    ],
  },
];

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(to) {
    if (to.hash) {
      return {
        el: to.hash,
        top: 80,
        behavior: "smooth",
      };
    }

    return {
      top: 0,
      left: 0,
      behavior: "smooth",
    };
  },
});

export default router
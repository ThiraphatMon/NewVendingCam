import axios from "axios";

const service = {}

var path = "/api/machines"

service.get_list = (filter = {}) => {
    return axios.get(
        `${import.meta.env.VITE_API_URL}${path}`,
        { params: filter }
    );
}

service.get_one = (machine_id,filter = {}) => {
    return axios.get(
        `${import.meta.env.VITE_API_URL}${path}/${machine_id}`,
        { params: filter }
    );
}

service.update = (machine_id,machine_update) => {
    return axios.patch(
        `${import.meta.env.VITE_API_URL}${path}/${machine_id}`,
        machine_update
    )
}

export default service;
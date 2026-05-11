import axios from "axios";

const service = {}

var path = "/api/machines"

service.get_list = (machine_id, filter = {}) => {
    return axios.get(
        `${import.meta.env.VITE_API_URL}${path}/${machine_id}`,
        { params: filter }
    );
}

export default service;
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
        `${import.meta.env.VITE_API_URL}${path}/${machine_id}/roi`,
        { params: filter }
    );
}

service.update = (machine_id,configuredROI) => {
    return axios.put(
        `${import.meta.env.VITE_API_URL}${path}/${machine_id}/roi`,
        configuredROI
    )
}

service.get_latest_image = (machine_id) => {
    return axios.get(
        `${import.meta.env.VITE_API_URL}${path}/${machine_id}/latest-image`
    );
}

export default service;
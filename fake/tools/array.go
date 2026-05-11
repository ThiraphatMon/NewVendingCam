package tools

type Array struct {
}

func (me Array) IncludeString(s []string, e string) bool {
	for _, v := range s {
		if v == e {
			return true
		}
	}
	return false
}

func (me Array) UniqueString(tmpSlice []string) []string {
	keys := make(map[string]bool)
	list := []string{}
	for _, entry := range tmpSlice {
		if _, value := keys[entry]; !value {
			keys[entry] = true
			list = append(list, entry)
		}
	}
	return list
}

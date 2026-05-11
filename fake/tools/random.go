package tools

import "math/rand"

type Random struct {
}

// const letterBytesaToZ = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
const letterBytesAToZ = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

func (me Random) AToZ(n int) string {
	b := make([]byte, n)
	for i := range b {
		b[i] = letterBytesAToZ[rand.Intn(len(letterBytesAToZ))]
	}
	return string(b)
}

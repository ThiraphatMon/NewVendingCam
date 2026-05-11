package tools

import "time"

type Date struct {
}

func (me Date) GetTodayStartEnd() (int64, int64) {
	now := time.Now()
	bangkokLoc, err := time.LoadLocation("Asia/Bangkok")
	if err != nil {
		panic("Failed to load Asia/Bangkok location!")
	}

	// Start of today: Set hour, minute, second, and nanosecond to 0
	startOfDay := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, bangkokLoc)

	// End of today: Start of tomorrow minus one nanosecond
	endOfDay := startOfDay.Add(24 * time.Hour).Add(-time.Nanosecond)

	return startOfDay.UnixMilli(), endOfDay.UnixMilli()
}

func (me Date) GetThisWeekStartEnd() (int64, int64) {
	now := time.Now()
	bangkokLoc, err := time.LoadLocation("Asia/Bangkok")
	if err != nil {
		panic("Failed to load Asia/Bangkok location!")
	}

	// Start of the week: Go back to the beginning of the current day,
	// then subtract days to reach Monday (assuming Monday is the start of the week).
	// time.Weekday() returns Sunday = 0, Monday = 1, ..., Saturday = 6
	offset := time.Duration(now.Weekday()-time.Monday) * 24 * time.Hour
	if now.Weekday() == time.Sunday { // Adjust for Sunday if it's considered the end of the week
		offset = 6 * 24 * time.Hour
	}
	startOfWeek := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, bangkokLoc).Add(-offset)

	// End of the week: Start of next week minus one nanosecond
	endOfWeek := startOfWeek.Add(7 * 24 * time.Hour).Add(-time.Nanosecond)

	return startOfWeek.UnixMilli(), endOfWeek.UnixMilli()
}

func (me Date) GetThisMonthStartEnd() (int64, int64) {
	now := time.Now()
	bangkokLoc, err := time.LoadLocation("Asia/Bangkok")
	if err != nil {
		panic("Failed to load Asia/Bangkok location!")
	}

	// Start of the month: Set day to 1, and hour, minute, second, nanosecond to 0
	startOfMonth := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, bangkokLoc)

	// End of the month: Start of next month minus one nanosecond
	endOfMonth := startOfMonth.AddDate(0, 1, 0).Add(-time.Nanosecond)

	return startOfMonth.UnixMilli(), endOfMonth.UnixMilli()
}

func (me Date) GetThisYearStartEnd() (int64, int64) {
	now := time.Now()
	bangkokLoc, err := time.LoadLocation("Asia/Bangkok")
	if err != nil {
		panic("Failed to load Asia/Bangkok location!")
	}
	// Start of the year: Set month to January, day to 1, and hour, minute, second, nanosecond to 0
	startOfYear := time.Date(now.Year(), time.January, 1, 0, 0, 0, 0, bangkokLoc)

	// End of the year: Start of next year minus one nanosecond
	endOfYear := startOfYear.AddDate(1, 0, 0).Add(-time.Nanosecond)

	return startOfYear.UnixMilli(), endOfYear.UnixMilli()
}

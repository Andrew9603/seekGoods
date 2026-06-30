const cities = [
  { name: '广州', lng: 113.26, lat: 23.13 },
  { name: '深圳', lng: 114.06, lat: 22.55 },
  { name: '上海', lng: 121.47, lat: 31.23 },
  { name: '北京', lng: 116.4, lat: 39.9 },
  { name: '成都', lng: 104.07, lat: 30.67 },
  { name: '武汉', lng: 114.3, lat: 30.59 },
  { name: '西安', lng: 108.94, lat: 34.26 },
  { name: '青岛', lng: 120.38, lat: 36.07 },
]

const statuses = ['on_order', 'waiting', 'resting', 'repositioning']

export const mockDrivers = Array.from({ length: 25 }, (_, index) => {
  const city = cities[index % cities.length]
  return {
    id: `D${String(index + 1).padStart(3, '0')}`,
    name: `司机 ${String(index + 1).padStart(3, '0')}`,
    city: city.name,
    lng: city.lng + ((index % 5) - 2) * 0.08,
    lat: city.lat + ((index % 3) - 1) * 0.06,
    status: statuses[index % statuses.length],
  }
})

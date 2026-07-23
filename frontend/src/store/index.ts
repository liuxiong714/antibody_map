import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface FilterState {
  disease: string;
  dataType: string;
  province: string;
  yearStart: number | null;
  yearEnd: number | null;
  ageMin: number | null;
  ageMax: number | null;
  gender: string;
  occupation: string;
  setDisease: (d: string) => void;
  setDataType: (t: string) => void;
  setProvince: (p: string) => void;
  setYearRange: (start: number | null, end: number | null) => void;
  setAgeRange: (min: number | null, max: number | null) => void;
  setGender: (g: string) => void;
  setOccupation: (o: string) => void;
  reset: () => void;
}

export const useFilterStore = create<FilterState>()(
  persist(
    (set) => ({
      disease: '',
      dataType: '',
      province: '',
      yearStart: null,
      yearEnd: null,
      ageMin: null,
      ageMax: null,
      gender: '',
      occupation: '',
      setDisease: (disease: string) => set({ disease }),
      setDataType: (dataType) => set({ dataType }),
      setProvince: (province) => set({ province }),
      setYearRange: (yearStart, yearEnd) => set({ yearStart, yearEnd }),
      setAgeRange: (ageMin, ageMax) => set({ ageMin, ageMax }),
      setGender: (gender) => set({ gender }),
      setOccupation: (occupation) => set({ occupation }),
      reset: () => set({
        disease: '', dataType: '', province: '',
        yearStart: null, yearEnd: null,
        ageMin: null, ageMax: null,
        gender: '', occupation: '',
      }),
    }),
    { name: 'antibody-filter-store' }
  )
);

export type ScalableGroup = {
  groups_total:number;
  groups_eligible:number;
  groups_suppressed:number;
  groups_shown:number;
  coverage_note:string;
  items:{name:string;spend:number;transactions:number;share_of_total:number}[];
};
export type ScalableSummary = {
  run_id:string;
  status:string;
  analysis_type:string;
  coverage:string;
  data_limitations:string[];
  metrics:{rows_scanned:number;valid_amount_rows:number;invalid_amount_rows:number;missing_cells:number;column_count:number;total_spend:number;supplier_count:number;category_count:number;dated_amount_rows:number};
  suppliers:ScalableGroup;
  categories:ScalableGroup;
  monthly_spend:{month:string;spend:number}[];
  duration_seconds:number;
  verification:string;
  source_stable:boolean;
};

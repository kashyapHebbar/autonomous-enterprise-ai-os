export type RiskScreeningResult={
  analysis_type:string;
  coverage:string;
  metrics:{rows_scanned:number;valid_amount_rows:number;invalid_amount_rows:number;total_amount_source_units:number};
  signals:{unusually_high_amount_transactions:number;repeated_transaction_pattern_groups:number;transactions_in_repeated_patterns:number;repeated_invoice_identifier_groups:number;transactions_in_repeated_invoice_groups:number;possible_split_pattern_groups:number;transactions_in_split_patterns:number};
  thresholds:{amount_iqr_upper_source_units:number|null};
  invoice_identifier_available:boolean;
  verification:string;
  limitations:string[];
  hugging_face_requests:number;
};
export type RiskScreeningJob={
  id?:string;run_id:string;status:'not_started'|'queued'|'running'|'cancel_requested'|'cancelled'|'interrupted'|'failed'|'completed';
  rows_scanned?:number;valid_amount_rows?:number;invalid_amount_rows?:number;
  progress_percent?:number;started_at?:string;updated_at?:string;
  result?:RiskScreeningResult|null;error?:string|null;
};

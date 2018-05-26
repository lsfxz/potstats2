export interface User {
  name: string;
  uid: number;
}

export interface PosterStats {
  User: User;
  uid: number;
  post_count: number;
  edit_count: number;
  avg_post_length:	number;
  threads_created:	number;
  quoted_count: number;
  quotes_count:	number;
}

export interface YearStats {
  year: number,
  post_count: number,
  edit_count: number,
  avg_post_length: number,
  threads_created: number
}

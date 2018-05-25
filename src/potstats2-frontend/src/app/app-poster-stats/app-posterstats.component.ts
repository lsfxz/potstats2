import { Component, OnInit, ViewChild } from '@angular/core';
import { MatPaginator, MatSort } from '@angular/material';
import { AppPosterstatsDataSource } from './app-posterstats-data-source';
import {PosterStatsService} from '../data/poster-stats.service';

@Component({
  selector: 'app-userstats',
  templateUrl: './app-posterstats.component.html',
  styleUrls: ['./app-posterstats.component.css']
})
export class AppPosterstatsComponent implements OnInit {
  @ViewChild(MatPaginator) paginator: MatPaginator;
  @ViewChild(MatSort) sort: MatSort;
  dataSource: AppPosterstatsDataSource;

  /** Columns displayed in the table. Columns IDs can be added, removed, or reordered. */
  displayedColumns = ['name', 'post_count', 'edit_count', 'avg_post_length', 'threads_created', 'quoted_count', 'quotes_count'];

  constructor(private service: PosterStatsService) { }
  ngOnInit() {
    this.dataSource = new AppPosterstatsDataSource(this.service, this.paginator, this.sort);
  }
}
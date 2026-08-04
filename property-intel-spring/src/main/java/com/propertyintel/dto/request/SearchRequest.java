package com.propertyintel.dto.request;

import lombok.AccessLevel;
import lombok.Data;
import lombok.experimental.FieldDefaults;

import java.util.List;

@Data
@FieldDefaults(level = AccessLevel.PRIVATE)
public class SearchRequest {
    List<String> districts;
    Long minPrice;
    Long maxPrice;
    String sort;

    String q;
    List<String> amenities;

    int page = 1;
    int size = 20;
}

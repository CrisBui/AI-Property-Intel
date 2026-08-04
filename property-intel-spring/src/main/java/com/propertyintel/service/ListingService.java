package com.propertyintel.service;

import com.propertyintel.dto.request.SearchRequest;
import com.propertyintel.dto.response.ListingCardResponse;
import com.propertyintel.dto.response.ListingDetailResponse;
import org.springframework.data.domain.Page;

public interface ListingService {
    Page<ListingCardResponse> searchListings(SearchRequest request);

    ListingDetailResponse getListingDetail(String sourceId);
}
